"""
Token-bucket rate limiting.

Each client has a bucket holding up to ``capacity`` tokens. A request
spends one token; tokens flow back in continuously at ``refill_per_second``
(e.g. one every 12 seconds), so short bursts are fine but a sustained flood
runs dry and is answered with 429 until the bucket refills. Only two numbers
are stored per client (tokens left and when they were last topped up), not
a list of request timestamps as DRF's built-in throttles keep.

Buckets live in Django's cache. With the default per-process cache each
worker keeps its own buckets; point CACHES at Redis or Memcached to share
them across workers.

Rates come from ``settings.RATE_LIMITS`` as ``{scope: (capacity, seconds
to refill the whole bucket)}`` and can be turned off with
``RATE_LIMIT_ENABLED = False``. ``_lock`` serialises the read-modify-write
of a bucket within this process.
"""

import math
import threading
import time

from django.conf import settings
from django.core.cache import cache
from rest_framework.throttling import BaseThrottle

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

_lock = threading.Lock()


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")

    if forwarded:
        return forwarded.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "") or "unknown"


class TokenBucketThrottle(BaseThrottle):
    scope: str = ""

    def __init__(self):
        self.capacity, refill_seconds = settings.RATE_LIMITS[self.scope]
        self.refill_per_second = self.capacity / refill_seconds
        self._wait = 0.0

    def get_key(self, request, view) -> str | None:
        """Who the bucket belongs to; None skips limiting for this request."""

        raise NotImplementedError

    def allow_request(self, request, view) -> bool:
        """
        Spend a token from the caller's bucket, refilling it first.

        Uses wall-clock time so buckets in a shared cache agree across
        workers. The bucket never refills beyond full, and its cache entry
        lives only until it would be full again, after which a fresh bucket
        is the same thing.
        """
        if not getattr(settings, "RATE_LIMIT_ENABLED", True):
            return True

        key = self.get_key(request, view)

        if key is None:
            return True

        cache_key = f"ratelimit:{self.scope}:{key}"
        now = time.time()

        with _lock:
            tokens, updated = cache.get(cache_key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - updated) * self.refill_per_second)

            if tokens >= 1:
                tokens -= 1
                allowed = True
            else:
                allowed = False
                self._wait = (1 - tokens) / self.refill_per_second

            ttl = math.ceil((self.capacity - tokens) / self.refill_per_second) + 1
            cache.set(cache_key, (tokens, now), ttl)

        return allowed

    def wait(self) -> float | None:
        return self._wait or None


class WriteRateThrottle(TokenBucketThrottle):
    """Every create, update and delete, per signed-in user (or IP)."""

    scope = "write"

    def get_key(self, request, view):
        if request.method in SAFE_METHODS:
            return None

        user = getattr(request, "user", None)

        if user is not None and user.is_authenticated:
            return f"user:{user.pk}"

        return f"ip:{client_ip(request)}"


class LoginIPRateThrottle(TokenBucketThrottle):
    """Sign-in attempts from one address, whatever account they try."""

    scope = "login_ip"

    def get_key(self, request, view):
        return client_ip(request) if request.method == "POST" else None


class LoginAccountRateThrottle(TokenBucketThrottle):
    """Sign-in attempts against one account, from anywhere."""

    scope = "login_account"

    def get_key(self, request, view):
        if request.method != "POST":
            return None

        try:
            identifier = request.data.get("email") or request.data.get("phone_number")
        except Exception:
            return None

        return str(identifier).strip().lower() if identifier else None


LOGIN_THROTTLES = [LoginIPRateThrottle, LoginAccountRateThrottle]


class ContactRateThrottle(TokenBucketThrottle):
    """Website contact form submissions from one address."""

    scope = "contact"

    def get_key(self, request, view):
        return client_ip(request) if request.method == "POST" else None
