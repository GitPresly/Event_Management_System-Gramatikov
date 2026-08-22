"""
Настройки на Django проекта „Система за управление на събития“.

Всички чувствителни стойности (таен ключ, достъп до базата, SMTP) се четат от
файл .env, за да не попадат в хранилището. Виж .env.example за образец.
"""
import os
import sys
from pathlib import Path

from django.contrib.messages import constants as message_constants
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Зареждане на .env файла, ако съществува
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    """Чете булева променлива на средата (приема true/1/yes/on)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    """Чете списък, разделен със запетаи, от променлива на средата."""
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Основни
# ---------------------------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-development-key-only")

DEBUG = env_bool("DEBUG", True)

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost")

# Базов адрес, използван при съставяне на абсолютни връзки в имейлите
SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:8000")

# ---------------------------------------------------------------------------
# Приложения
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Приложения на проекта — всяко отговаря на един модул от заданието
    "accounts",         # роли и автентикация (Django Auth)
    "events",           # модул „Събития“
    "registration",     # модул „Регистрация“ (билети, QR, симулация на плащане)
    "checkin",          # модул „На място“ (check-in чрез QR)
    "notifications",    # модул „Комуникация“ (имейли)
    "reports",          # модул „Отчети“
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# База данни — PostgreSQL съгласно заданието
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "event_management"),
        "USER": os.getenv("DB_USER", "ems_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "5432"),
        # Поддържане на отворени връзки — намалява натоварването при
        # голям брой едновременни регистрации.
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            # Не изчакваме безкрайно при заключен ред по време на резервация.
            "options": "-c lock_timeout=5000",
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Автентикация (Django Auth)
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "events:event_list"

# ---------------------------------------------------------------------------
# Локализация
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "bg"
TIME_ZONE = "Europe/Sofia"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Статични и медийни файлове
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Имейл
# ---------------------------------------------------------------------------

if DEBUG:
    # В режим на разработка писмата се извеждат в конзолата вместо да се изпращат.
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    "Система за управление на събития <no-reply@events.local>",
)

# ---------------------------------------------------------------------------
# Сигурност
# ---------------------------------------------------------------------------

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# Django нарича класа на грешките "error", а Bootstrap го нарича "danger" —
# това преименуване позволява съобщенията да се оцветяват правилно в шаблона.
MESSAGE_TAGS = {message_constants.ERROR: "danger"}

SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

if not DEBUG:
    # В продукция бисквитките се предават само по HTTPS.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    # HSTS указва на браузъра да ползва само HTTPS за този домейн.
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# ---------------------------------------------------------------------------
# Специфични за приложението настройки
# ---------------------------------------------------------------------------

# Максимален брой билети, които един участник може да заяви в една регистрация.
MAX_TICKETS_PER_REGISTRATION = int(os.getenv("MAX_TICKETS_PER_REGISTRATION", "10"))

# Колко часа преди началото на събитието се изпраща напомняне по подразбиране.
REMINDER_HOURS_BEFORE = int(os.getenv("REMINDER_HOURS_BEFORE", "24"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
    },
}

# При изпълнение на тестовете информационните съобщения се заглушават, за да
# остане четим само резултатът от самите тестове.
if "test" in sys.argv:
    LOGGING["root"]["level"] = "WARNING"
