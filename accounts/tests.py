from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from common.choices import UserRole


class AuthCookieTests(TestCase):
    """The installed app must stay signed in after it is closed and reopened."""

    def setUp(self):
        cache.clear()
        self.user = User(email="t@x.com", name="T", role=UserRole.TEACHER)
        self.user.set_password("Secret-pass-99")
        self.user.save()
        self.client = APIClient()

    def login(self):
        return self.client.post(
            reverse("login"), {"email": "t@x.com", "password": "Secret-pass-99"}, format="json"
        )

    def assert_persistent(self, response):
        access = response.cookies[settings.JWT_ACCESS_COOKIE]
        refresh = response.cookies[settings.JWT_REFRESH_COOKIE]
        lifetime = settings.SIMPLE_JWT

        self.assertEqual(int(access["max-age"]), int(lifetime["ACCESS_TOKEN_LIFETIME"].total_seconds()))
        self.assertEqual(int(refresh["max-age"]), int(lifetime["REFRESH_TOKEN_LIFETIME"].total_seconds()))
        self.assertTrue(access["httponly"])
        self.assertTrue(refresh["httponly"])

    def test_login_cookies_outlive_the_browser_session(self):
        response = self.login()
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_persistent(response)

    def test_refresh_keeps_cookies_persistent(self):
        self.login()
        response = self.client.post(reverse("refresh"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_persistent(response)

    def test_refresh_token_lasts_longer_than_access_token(self):
        lifetime = settings.SIMPLE_JWT
        self.assertGreater(lifetime["REFRESH_TOKEN_LIFETIME"], lifetime["ACCESS_TOKEN_LIFETIME"])

    def test_logout_still_clears_cookies(self):
        self.login()
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies[settings.JWT_ACCESS_COOKIE].value, "")
        self.assertEqual(response.cookies[settings.JWT_REFRESH_COOKIE].value, "")
