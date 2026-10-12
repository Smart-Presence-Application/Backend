"""
Django settings for SmartPresence.

Every value comes from the environment (or a .env file) through
python-decouple; see .env.example for development and
.env.production.example for production.

DEBUG=False switches on production behaviour: Cloudinary media storage,
HTTPS (redirects, secure cookies, HSTS) and Brevo SMTP defaults for email.
"""

import sys
from datetime import timedelta
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent
RUNNING_TESTS = "test" in sys.argv[1:2]

SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "cloudinary",
    "cloudinary_storage",
    "common",
    "accounts",
    "schools",
    "academics",
    "teachers",
    "students",
    "attendance_student",
    "attendance_teacher",
    "parents",
    "notifications",
    "reports",
    "system",
    "website",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "common.middleware.RequestIDMiddleware",
    "system.middleware.MaintenanceModeMiddleware",
    "system.middleware.ActivityLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_USER_MODEL = "accounts.User"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST"),
        "PORT": config("DB_PORT"),
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"sslmode": config("DB_SSLMODE", default="prefer")},
    }
}

AI_SERVICE_URL = config("AI_SERVICE_URL")
AI_SERVICE_API_KEY = config("AI_SERVICE_API_KEY", default="")
AI_JOB_WORKERS = config("AI_JOB_WORKERS", default=2, cast=int)
AI_JOB_STALE_AFTER = config("AI_JOB_STALE_AFTER", default=1200, cast=int)
AI_JOB_RETENTION_DAYS = config("AI_JOB_RETENTION_DAYS", default=7, cast=int)
AI_JOBS_RUN_INLINE = config("AI_JOBS_RUN_INLINE", default=False, cast=bool) or RUNNING_TESTS

SUPERUSER_EMAIL = config("SUPERUSER_EMAIL", default="")
SUPERUSER_PASSWORD = config("SUPERUSER_PASSWORD", default="")
SUPERUSER_NAME = config("SUPERUSER_NAME", default="Smart Presence Admin")

RATE_LIMIT_ENABLED = config("RATE_LIMIT_ENABLED", default=True, cast=bool) and not RUNNING_TESTS
RATE_LIMITS = {
    "write": (60, 60),
    "login_ip": (20, 600),
    "login_account": (5, 300),
    "contact": (5, 600),
}

CONTACT_RECIPIENT_EMAIL = config("CONTACT_RECIPIENT_EMAIL", default="")
TURNSTILE_SECRET_KEY = config("TURNSTILE_SECRET_KEY", default="")
ACTIVITY_LOG_RETENTION_DAYS = config("ACTIVITY_LOG_RETENTION_DAYS", default=90, cast=int)
FRONTEND_URL = config("FRONTEND_URL", default="")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"verbose": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "verbose"}},
    "root": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO")},
    "loggers": {"django": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}

USE_HTTPS = config("USE_HTTPS", default=not DEBUG, cast=bool)
if USE_HTTPS:
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=3600, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool)
    SECURE_HSTS_PRELOAD = False
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = config("EMAIL_HOST", default="smtp-relay.brevo.com")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_TIMEOUT = config("EMAIL_TIMEOUT", default=20, cast=int)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Smart Presence <no-reply@example.com>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

USE_CLOUDINARY = config("USE_CLOUDINARY", default=not DEBUG, cast=bool)
CLOUDINARY_STORAGE = {
    "CLOUD_NAME": config("CLOUDINARY_CLOUD_NAME", default=""),
    "API_KEY": config("CLOUDINARY_API_KEY", default=""),
    "API_SECRET": config("CLOUDINARY_API_SECRET", default=""),
    "SECURE": True,
}

STORAGES = {
    "default": {
        "BACKEND": "common.media_storage.OptimizedCloudinaryStorage"
        if USE_CLOUDINARY
        else "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

CORS_ALLOWED_ORIGINS = config("CORS_ALLOWED_ORIGINS", cast=Csv())
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ["Content-Disposition"]
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv()) or CORS_ALLOWED_ORIGINS

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.CookieJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardResultsPagination",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "EXCEPTION_HANDLER": "common.exceptions.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "common.throttling.WriteRateThrottle",
    ],
    "PAGE_SIZE": config("PAGE_SIZE", default=20, cast=int),
}

JWT_ACCESS_COOKIE = "access_token"
JWT_REFRESH_COOKIE = "refresh_token"
JWT_COOKIE_SECURE = USE_HTTPS
JWT_COOKIE_HTTP_ONLY = True
JWT_COOKIE_SAMESITE = config("JWT_COOKIE_SAMESITE", default="Lax")
JWT_COOKIE_PATH = "/"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

VAPID_PUBLIC_KEY = config("VAPID_PUBLIC_KEY", default="")
VAPID_PRIVATE_KEY = config("VAPID_PRIVATE_KEY", default="")
VAPID_SUBJECT = config("VAPID_SUBJECT", default="mailto:admin@smartpresence.app")
