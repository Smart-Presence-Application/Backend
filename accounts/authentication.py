"""JWT authentication that reads only HttpOnly cookies."""
from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken


class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        raw_token = request.COOKIES.get(settings.JWT_ACCESS_COOKIE)
        if raw_token is None:
            return None
        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token


def generate_pair(user) -> dict[str, str]:
    """Generate an access/refresh token pair for a user."""
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


def blacklist(refresh_token: str | RefreshToken | None) -> None:
    """Blacklist a refresh token when token blacklist support is enabled."""
    if not refresh_token:
        return
    token = refresh_token if isinstance(refresh_token, RefreshToken) else RefreshToken(refresh_token)
    token.blacklist()


def rotate_refresh(refresh_token: str) -> dict[str, str]:
    """Refresh an access token and optionally rotate the refresh token."""
    refresh = RefreshToken(refresh_token)
    tokens = {"access": str(refresh.access_token), "refresh": str(refresh)}
    if settings.SIMPLE_JWT.get("ROTATE_REFRESH_TOKENS"):
        if settings.SIMPLE_JWT.get("BLACKLIST_AFTER_ROTATION"):
            refresh.blacklist()
        refresh.set_jti()
        refresh.set_exp()
        refresh.set_iat()
        tokens["refresh"] = str(refresh)
    return tokens


def set_token_cookie(response, key: str, value: str, max_age: int | None = None) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=max_age,
        secure=settings.JWT_COOKIE_SECURE,
        httponly=settings.JWT_COOKIE_HTTP_ONLY,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path=settings.JWT_COOKIE_PATH,
    )


def delete_token_cookie(response, key: str) -> None:
    response.delete_cookie(key=key, path=settings.JWT_COOKIE_PATH, samesite=settings.JWT_COOKIE_SAMESITE)
