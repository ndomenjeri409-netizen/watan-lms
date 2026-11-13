from pathlib import Path

import dj_database_url
import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.is_file():
    environ.Env.read_env(env_file)

SECRET_KEY = env("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "django_filters",
    "corsheaders",
    "apps.accounts",
    "apps.org",
    "apps.audit",
    "apps.academics",
    "apps.files",
    "apps.cms",
    "apps.people",
    "apps.enrollment",
    "apps.scheduling",
    "apps.attendance",
    "apps.assessment",
    "apps.finance",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"
AUTH_USER_MODEL = "accounts.User"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        conn_max_age=0,
        ssl_require=env.bool("DB_SSL_REQUIRE", True),
    )
}
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.FirebaseAuthentication"
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.StandardPagination",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "300/min"},
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Watan LMS API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"]
)
FIREBASE_SERVICE_ACCOUNT_JSON = env("FIREBASE_SERVICE_ACCOUNT_JSON", default="")
COURSE_VIDEO_ALLOWED_HOSTS = env.list(
    "COURSE_VIDEO_ALLOWED_HOSTS",
    default=["youtube.com", "youtu.be", "vimeo.com"],
)

STORAGE_ENDPOINT_URL = env(
    "STORAGE_ENDPOINT_URL",
    default=env("B2_ENDPOINT_URL", default=env("R2_ENDPOINT_URL", default="")),
)
STORAGE_BUCKET = env(
    "STORAGE_BUCKET", default=env("B2_BUCKET", default=env("R2_BUCKET", default=""))
)
STORAGE_ACCESS_KEY_ID = env(
    "STORAGE_ACCESS_KEY_ID",
    default=env("B2_ACCESS_KEY_ID", default=env("R2_ACCESS_KEY_ID", default="")),
)
STORAGE_SECRET_ACCESS_KEY = env(
    "STORAGE_SECRET_ACCESS_KEY",
    default=env(
        "B2_SECRET_ACCESS_KEY", default=env("R2_SECRET_ACCESS_KEY", default="")
    ),
)
STORAGE_REGION = env(
    "STORAGE_REGION", default=env("B2_REGION", default=env("R2_REGION", default=""))
)

R2_ENDPOINT_URL = STORAGE_ENDPOINT_URL
R2_BUCKET = STORAGE_BUCKET
R2_ACCESS_KEY_ID = STORAGE_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY = STORAGE_SECRET_ACCESS_KEY
R2_REGION = STORAGE_REGION
B2_ENDPOINT_URL = STORAGE_ENDPOINT_URL
B2_BUCKET = STORAGE_BUCKET
B2_ACCESS_KEY_ID = STORAGE_ACCESS_KEY_ID
B2_SECRET_ACCESS_KEY = STORAGE_SECRET_ACCESS_KEY
B2_REGION = STORAGE_REGION
FILE_STORAGE_QUOTA_BYTES = env.int(
    "FILE_STORAGE_QUOTA_BYTES", default=500 * 1024 * 1024
)
