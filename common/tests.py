from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

LOGIN = "/api/auth/login/"


@override_settings(RATE_LIMIT_ENABLED=True)
class TokenBucketThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def tearDown(self):
        cache.clear()

    def attempt(self, email="someone@example.com"):
        return self.client.post(LOGIN, {"email": email, "password": "wrong-password"}, format="json")

    @override_settings(RATE_LIMITS={"write": (60, 60), "login_ip": (20, 600), "login_account": (3, 300)})
    def test_account_bucket_runs_dry_then_blocks(self):
        """Once blocked, another account still has its own bucket."""
        self.assertEqual([self.attempt().status_code for _ in range(3)], [400, 400, 400])

        blocked = self.attempt()

        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked)
        self.assertIn("Too many requests", blocked.json()["message"])
        self.assertEqual(self.attempt("other@example.com").status_code, 400)

    @override_settings(RATE_LIMITS={"write": (60, 60), "login_ip": (2, 600), "login_account": (10, 300)})
    def test_ip_bucket_covers_every_account(self):
        self.attempt("a@example.com")
        self.attempt("b@example.com")

        self.assertEqual(self.attempt("c@example.com").status_code, 429)

    @override_settings(RATE_LIMITS={"write": (60, 60), "login_ip": (20, 600), "login_account": (1, 300)})
    def test_tokens_refill_over_time(self):
        """One token refills every 300 seconds."""
        from unittest import mock

        with mock.patch("common.throttling.time.time", return_value=1_000.0):
            self.assertEqual(self.attempt().status_code, 400)
            self.assertEqual(self.attempt().status_code, 429)

        with mock.patch("common.throttling.time.time", return_value=1_301.0):
            self.assertEqual(self.attempt().status_code, 400)
