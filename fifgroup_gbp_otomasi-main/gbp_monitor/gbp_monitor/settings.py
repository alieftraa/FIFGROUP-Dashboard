"""
settings.py — Konfigurasi Django untuk GBP Monitor.
Menggunakan django-environ dan dj-database-url.
Siap untuk development (SQLite fallback) dan production (Supabase PostgreSQL).
"""

from pathlib import Path
import environ
import dj_database_url

# ── Base ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DATABASE_URL=(str, f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
)

environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env(
    "SECRET_KEY",
    default="django-insecure-gbp-monitor-dev-key-change-in-production-xyz123",
)

DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# ── Aplikasi ────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # GBP Monitor
    "gbp.apps.GbpConfig",
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

ROOT_URLCONF = "gbp_monitor.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "gbp_monitor.wsgi.application"
ASGI_APPLICATION = "gbp_monitor.asgi.application"

# ── Database ─────────────────────────────────────────────────────────
# Default: SQLite (development). Untuk Supabase, set DATABASE_URL di .env:
# DATABASE_URL=postgresql://postgres:<password>@<host>:5432/postgres
_db_url = env("DATABASE_URL")
_is_postgres = _db_url.startswith("postgresql://") or _db_url.startswith("postgres://")

DATABASES = {
    "default": dj_database_url.config(
        default=_db_url,
        conn_max_age=600,
        ssl_require=_is_postgres,  # SSL aktif hanya untuk PostgreSQL (Supabase)
    )
}

# ── Auth ─────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Internasionalisasi ────────────────────────────────────────────────
LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"
USE_I18N = True
USE_TZ = True

# ── Static Files ─────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "gbp" / "static",
]

# ── Default Primary Key ───────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── GBP API Config ────────────────────────────────────────────────────
# Single source of truth: semua data OAuth tersimpan di BASE_DIR/data/
# BASE_DIR = gbp_monitor/ (lokasi manage.py)
GBP_DATA_DIR = BASE_DIR / "data"

def _resolve_gbp_path(env_value: str, fallback: "Path") -> "Path":
    """
    Resolve path credential/token ke absolute path.

    Jika ENV berisi relative path (misal: 'data/credentials.json'),
    resolve relatif terhadap BASE_DIR (bukan CWD saat runtime).
    Jika sudah absolute, gunakan langsung.
    """
    from pathlib import Path as _Path
    p = _Path(env_value)
    if p.is_absolute():
        return p.resolve()
    # Relative path → resolve relatif terhadap BASE_DIR
    return (BASE_DIR / p).resolve()

_raw_cred = env("GBP_CREDENTIALS_PATH", default="")
_raw_token = env("GBP_TOKEN_PATH", default="")

GBP_CREDENTIALS_PATH = _resolve_gbp_path(_raw_cred, GBP_DATA_DIR / "credentials.json") \
    if _raw_cred else (GBP_DATA_DIR / "credentials.json").resolve()

GBP_TOKEN_PATH = _resolve_gbp_path(_raw_token, GBP_DATA_DIR / "token.json") \
    if _raw_token else (GBP_DATA_DIR / "token.json").resolve()

GBP_DEFAULT_ACCOUNT_ID = env("GBP_DEFAULT_ACCOUNT_ID", default="")

# Pastikan direktori data/ selalu ada (dibuat otomatis jika belum ada)
GBP_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────
_LOGS_DIR = BASE_DIR / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} [{levelname}] {name}: {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": str(_LOGS_DIR / "django.log"),
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "gbp": {
            "handlers": ["console", "file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}
