"""Reusable helper utilities."""
import secrets
import string
from decouple import config


def generate_random_password(length: int = config("PASSWORD_LENGTH", default=12, cast=int)) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))
