import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DJANGO_DEBUG", "1").lower() in {"1", "true", "yes", "on"}
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")

if not DEBUG and SECRET_KEY == "dev-only-change-me":
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY before starting Sovietgram in production.")


def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

SOVIETGRAM_RATE_LIMITS = {
    "send_message": {
        "limit": int(os.getenv("RATE_LIMIT_SEND_PER_MINUTE", "30")),
        "window": 60,
    },
    "search_messages": {
        "limit": int(os.getenv("RATE_LIMIT_SEARCH_PER_MINUTE", "60")),
        "window": 60,
    },
    "global_search": {
        "limit": int(os.getenv("RATE_LIMIT_GLOBAL_SEARCH_PER_MINUTE", "90")),
        "window": 60,
    },
    "typing": {
        "limit": int(os.getenv("RATE_LIMIT_TYPING_PER_MINUTE", "120")),
        "window": 60,
    },
}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts.apps.AccountsConfig",
    "apps.messenger.apps.MessengerConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.accounts.timezone.ClientTimezoneMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.UserActivityMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
                "config.context_processors.static_version",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

RUNTIME_DIR = BASE_DIR / "var"
RUNTIME_DIR.mkdir(exist_ok=True)

if os.getenv("DB_ENGINE", "sqlite").lower() in {"postgres", "postgresql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "sovietgram"),
            "USER": os.getenv("POSTGRES_USER", "sovietgram"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": RUNTIME_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["apps.accounts.backends.EmailOrUsernameBackend"]

LANGUAGE_CODE = "ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = RUNTIME_DIR / "static"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
        ),
    },
}
MEDIA_URL = "/media/"
MEDIA_ROOT = RUNTIME_DIR / "media"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "messenger:home"
LOGOUT_REDIRECT_URL = "accounts:login"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Outgoing transactional mail (Brevo SMTP relay). Never store SMTP
# credentials in source control; production reads them from /opt/sovietgram/.env.
# Local development prints messages to the console rather than sending them.
EMAIL_BACKEND = os.getenv(
    "DJANGO_EMAIL_BACKEND",
    (
        "django.core.mail.backends.console.EmailBackend"
        if DEBUG
        else "django.core.mail.backends.smtp.EmailBackend"
    ),
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp-relay.brevo.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1").strip().lower() in {
    "1", "true", "yes", "on",
}
EMAIL_USE_SSL = False
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "15"))

# Safe rollout: deploy and migrate first, enable after a successful live
# email verification smoke test. Existing accounts remain usable.
SOVIETGRAM_REQUIRE_EMAIL_VERIFICATION = os.getenv(
    "SOVIETGRAM_REQUIRE_EMAIL_VERIFICATION", "0"
).lower() in {"1", "true", "yes", "on"}
# Use the canonical public HTTPS origin for links sent by email. In production,
# this avoids depending on proxy scheme detection when building absolute URLs.
SOVIETGRAM_PUBLIC_URL = os.getenv(
    "SOVIETGRAM_PUBLIC_URL",
    "" if DEBUG else "https://sovietgram.su",
).strip().rstrip("/")
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", "Sovietgram <noreply@sovietgram.su>",
)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
