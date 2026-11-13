> SUPERSEDED by MASTER_GUIDE.md; do not follow.

# Sprint 0 — Foundation (Watan LMS v2)

Companion to `WATAN_LMS_V2_BLUEPRINT.md`. Follow the steps in order. Tick each box only when its check passes.

**Goal:** a logged-in user (Firebase) opens the React app, which calls `GET /api/v1/me` on the Django API through a **generated typed client** and shows their profile. CI is green. Staging DB and file bucket exist.

**Decisions already made:** roles `SUPER_ADMIN, ADMIN, DIRECTOR, HOD, TEACHER, BURSAR, STUDENT` · Django + DRF + PostgreSQL · Firebase Auth for login only · private R2 bucket for files · API JSON uses **snake_case** end to end (no camelCase transform layer; fewer moving parts).

## Rules for Copilot
1. Create exactly the files listed; don't invent extra apps or features.
2. `AUTH_USER_MODEL` must be set **before the first `migrate`** (step 3.5). Never change it later.
3. Never commit secrets. `.env` files are git-ignored; commit only `.env.example`.
4. Generated files (`backend/openapi.yaml`, `frontend/src/api/schema.d.ts`) are produced by commands, never hand-edited.
5. Run the verification command at the end of each step before moving on.

---

## Step 1 — Accounts and prerequisites (manual, ~30 min)

- [ ] Install: Python 3.12, Node 22 LTS, Docker Desktop, Git, GitHub account.
- [ ] **Firebase:** reuse the existing Firebase project (so existing logins keep working). Authentication → keep Email/Password enabled. Generate a **new** service-account key (Project settings → Service accounts) and revoke the old one. Save the JSON outside the repo.
- [ ] **Neon:** create a project named `watan-lms-staging`. Copy the **pooled** connection string (`...-pooler...`). It must include `sslmode=require`.
- [ ] **BackBlaze B2 Cloud Storage:** create a **private** bucket `watan-lms`. Create an API token scoped to *Object Read & Write* on that bucket only. Add CORS rules allowing `PUT` and `GET` from `http://localhost:3000` (add production origins later), allowed headers `*`, max age 3600. Do **not** enable the public development URL. (Check whether signup asks for a payment method.)
- [ ] **GitHub:** create repo `watan-lms-v2` (private).

**Check:** you have `DATABASE_URL`, the Firebase JSON, and the BackBlaze B2 values saved in a password manager.

---

## Step 2 — Repository scaffold

```
watan-lms-v2/
├─ backend/
├─ frontend/
├─ .github/workflows/ci.yml
├─ docker-compose.yml
├─ .gitignore
├─ .editorconfig
├─ .pre-commit-config.yaml
└─ README.md
```

- [ ] `git init`, add `.gitignore` containing at least: `.env`, `.env.*` (except `!.env.example`), `__pycache__/`, `.venv/`, `node_modules/`, `dist/`, `*.log`, `firebase-service-account*.json`, `.DS_Store`.
- [ ] `.editorconfig`: UTF-8, LF, 2-space indent (4 for `*.py`).
- [ ] `.pre-commit-config.yaml`: hooks for `ruff` (lint + format) and `detect-private-key`; frontend hooks run via `lint-staged` later (optional).
- [ ] `README.md`: one paragraph + "how to run" (filled in at the end of this sprint).

**Check:** `git status` shows no secret files.

---

## Step 3 — Backend

### 3.1 Create the project
```bash
mkdir -p backend && cd backend
python3.12 -m venv .venv && source .venv/bin/activate
mkdir requirements
```

`requirements/base.txt`
```
Django>=5.1,<5.3
djangorestframework>=3.15
drf-spectacular>=0.27
django-filter>=24.0
django-cors-headers>=4.4
dj-database-url>=2.2
django-environ>=0.11
psycopg[binary]>=3.2
firebase-admin>=6.5
boto3>=1.35
gunicorn>=22.0
whitenoise>=6.7
```
`requirements/dev.txt`
```
-r base.txt
pytest>=8.0
pytest-django>=4.8
factory-boy>=3.3
ruff>=0.6
```
```bash
pip install -r requirements/dev.txt
django-admin startproject config .
mkdir -p apps/accounts common
touch apps/__init__.py common/__init__.py
python manage.py startapp accounts apps/accounts
```
> The target folder must exist before `startapp` (done by `mkdir` above). Then set `name = "apps.accounts"` in `apps/accounts/apps.py`.

Split settings: move `config/settings.py` to `config/settings/base.py`; add `config/settings/__init__.py` (empty), `dev.py`, `prod.py`. Update `manage.py`, `wsgi.py`, `asgi.py` to use `config.settings.dev` by default (production sets `DJANGO_SETTINGS_MODULE=config.settings.prod`).

### 3.2 `config/settings/base.py` (key parts)
```python
import environ
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework", "drf_spectacular", "django_filters", "corsheaders",
    "apps.accounts",
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
AUTH_USER_MODEL = "accounts.User"          # MUST be set before the first migrate
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages"]},
}]
WSGI_APPLICATION = "config.wsgi.application"

import dj_database_url
DATABASES = {"default": dj_database_url.config(env="DATABASE_URL", conn_max_age=0, ssl_require=env.bool("DB_SSL_REQUIRE", True))}
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True   # required behind transaction poolers

LANGUAGE_CODE = "en"
TIME_ZONE = "Africa/Nairobi"
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.FirebaseAuthentication"],
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
SPECTACULAR_SETTINGS = {"TITLE": "Watan LMS API", "VERSION": "1.0.0", "SERVE_INCLUDE_SCHEMA": False}

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"])

FIREBASE_SERVICE_ACCOUNT_JSON = env("FIREBASE_SERVICE_ACCOUNT_JSON", default="")

R2_ENDPOINT_URL = env("R2_ENDPOINT_URL", default="")
R2_BUCKET = env("R2_BUCKET", default="")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
```
`dev.py`: `from .base import *`; `DEBUG = True`; `ALLOWED_HOSTS = ["*"]`.
`prod.py`: `from .base import *`; add `SECURE_SSL_REDIRECT = True`, `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`, `SECURE_HSTS_SECONDS = 31536000`, `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`.

`backend/.env.example` (commit) and `backend/.env` (git-ignored):
```
SECRET_KEY=change-me
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/watan
DB_SSL_REQUIRE=False
FIREBASE_SERVICE_ACCOUNT_JSON=
CORS_ALLOWED_ORIGINS=http://localhost:3000
R2_ENDPOINT_URL=
R2_BUCKET=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
```
(Local uses the Docker Postgres; staging uses the Neon pooled URL with `DB_SSL_REQUIRE=True`.)

### 3.3 `common/` utilities
- [ ] `common/models.py`
```python
import uuid
from django.db import models

class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True
```
- [ ] `common/pagination.py`
```python
from rest_framework.pagination import PageNumberPagination

class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
```
- [ ] `common/exceptions.py` — wrap DRF's handler to return `{"code": ..., "message": ..., "fields": {...}}` with codes `PERMISSION_DENIED`, `NOT_FOUND`, `VALIDATION`, `AUTHENTICATION`, `THROTTLED`, `UNKNOWN`.
- [ ] `common/scoping.py`
```python
from django.db import models

class ScopedQuerySet(models.QuerySet):
    """Every domain queryset implements for_user(); viewsets must call it."""
    def for_user(self, user):
        raise NotImplementedError

class ScopedViewSetMixin:
    """Use on every ModelViewSet: guarantees row-level scoping."""
    def get_queryset(self):
        return super().get_queryset().for_user(self.request.user)
```
- [ ] `common/money.py` — `quantize_money(Decimal) -> Decimal` (2 dp, `ROUND_HALF_UP`) and a `MoneyField` helper (`DecimalField(max_digits=12, decimal_places=2)`).
- [ ] `common/health.py` — `healthz` (always 200) and `readyz` (runs `SELECT 1`, returns 503 on failure).

### 3.4 Roles (`apps/accounts/roles.py`)
```python
from django.db import models

class Role(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    DIRECTOR = "DIRECTOR"
    HOD = "HOD"
    TEACHER = "TEACHER"
    BURSAR = "BURSAR"
    STUDENT = "STUDENT"

STAFF_ROLES = {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR, Role.HOD, Role.TEACHER, Role.BURSAR}
ADMIN_ROLES = {Role.SUPER_ADMIN, Role.ADMIN}
```

### 3.5 User model (`apps/accounts/models.py`) — before first migration
```python
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from common.models import BaseModel
from .roles import Role

class UserManager(BaseUserManager):
    def create_user(self, firebase_uid, email="", **extra):
        user = self.model(firebase_uid=firebase_uid, email=email, **extra)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, firebase_uid, password=None, **extra):
        extra.setdefault("is_staff", True); extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.SUPER_ADMIN)
        user = self.model(firebase_uid=firebase_uid, **extra)
        user.set_password(password)           # lets you log in to /admin with a password
        user.save(using=self._db)
        return user

class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    firebase_uid = models.CharField(max_length=128, unique=True)
    email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, null=True, blank=True)  # null = awaiting approval
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)   # Django admin access only

    USERNAME_FIELD = "firebase_uid"
    objects = UserManager()

    def __str__(self): return self.email or self.firebase_uid
```
Register in `admin.py` (`UserAdmin` minimal: list `email, role, is_active`).

### 3.6 Firebase authentication (`apps/accounts/authentication.py`)
Lazy initialization so tests and imports never need real credentials:
```python
import json
import firebase_admin
from django.conf import settings
from firebase_admin import auth as fb_auth, credentials
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import User

def _ensure_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON))
        firebase_admin.initialize_app(cred)

class FirebaseAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        _ensure_firebase()
        try:
            decoded = fb_auth.verify_id_token(header[7:])
        except Exception:
            raise AuthenticationFailed("Invalid or expired session")
        user, _ = User.objects.get_or_create(
            firebase_uid=decoded["uid"],
            defaults={"email": decoded.get("email", ""), "display_name": decoded.get("name", ""), "role": None},
        )
        if not user.is_active:
            raise AuthenticationFailed("Account disabled")
        return (user, decoded)

    def authenticate_header(self, request):
        return "Bearer"
```

### 3.7 `/me` endpoint
- [ ] `apps/accounts/serializers.py`: `MeSerializer` (read-only) with `id, email, display_name, role, is_active`.
- [ ] `apps/accounts/views.py`: `MeView(APIView)` → `GET` returns `MeSerializer(request.user).data`. Add `@extend_schema(responses=MeSerializer)` for the OpenAPI schema.
- [ ] `apps/accounts/urls.py`: `path("me", MeView.as_view())`.
- [ ] `config/urls.py`:
```python
from django.contrib import admin
from django.urls import include, path
from common.health import healthz, readyz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("readyz", readyz),
    path("api/v1/", include("apps.accounts.urls")),
]
```

### 3.8 Docker Compose (repo root `docker-compose.yml`)
```yaml
services:
  db:
    image: postgres:16
    environment: { POSTGRES_PASSWORD: postgres, POSTGRES_DB: watan }
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
  minio:                       # local S3-compatible storage
    image: minio/minio
    command: server /data --console-address ":9001"
    environment: { MINIO_ROOT_USER: minio, MINIO_ROOT_PASSWORD: minio12345 }
    ports: ["9000:9000", "9001:9001"]
    volumes: [miniodata:/data]
volumes: { pgdata: {}, miniodata: {} }
```
`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements/base.txt requirements/base.txt
RUN pip install --no-cache-dir -r requirements/base.txt
COPY . .
RUN python manage.py collectstatic --noinput
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
```

### 3.9 Migrate and run
```bash
docker compose up -d db
python manage.py makemigrations accounts
python manage.py migrate
python manage.py runserver
```
**Check:** `curl localhost:8000/healthz` → 200; `curl localhost:8000/readyz` → 200; `curl localhost:8000/api/v1/me` → 401 (no token).

### 3.10 Tests (`backend/tests/`)
Add `pytest.ini`: `DJANGO_SETTINGS_MODULE = config.settings.dev`, `python_files = tests.py test_*.py`.
- [ ] `test_health.py`: `/healthz` and `/readyz` return 200.
- [ ] `test_me.py`:
  - no header → 401;
  - invalid token (monkeypatch `fb_auth.verify_id_token` to raise) → 401;
  - valid token (monkeypatch to return `{"uid": "u1", "email": "a@b.com"}`) → 200, creates a `User` with `role=None`;
  - inactive user → 401.
- [ ] `test_scoping.py`: a tiny model/queryset proving `ScopedViewSetMixin` calls `for_user`.
**Check:** `pytest` passes.

### 3.11 OpenAPI file
```bash
python manage.py spectacular --file openapi.yaml --validate
```
Commit `backend/openapi.yaml`.
**Check:** the file contains `/api/v1/me` and the `Me` schema.

---

## Step 4 — Frontend

### 4.1 Create the project
```bash
cd .. && npm create vite@latest frontend -- --template react-ts && cd frontend
npm i react-router-dom @tanstack/react-query firebase openapi-fetch react-hook-form zod lucide-react tailwindcss @tailwindcss/vite
npm i -D openapi-typescript vitest @testing-library/react @testing-library/jest-dom jsdom
```
- [ ] `vite.config.ts`: add the `@tailwindcss/vite` plugin; dev server `port: 3000`.
- [ ] `src/index.css`: `@import "tailwindcss";` plus design-token CSS variables (colour, radius, spacing). Start with black/white/gold from the v1 branding plan; tokens only, no components yet.
- [ ] `.env.example` and `.env.local` (git-ignored):
```
VITE_API_URL=http://localhost:8000
VITE_FIREBASE_API_KEY=
VITE_FIREBASE_AUTH_DOMAIN=
VITE_FIREBASE_PROJECT_ID=
VITE_FIREBASE_APP_ID=
```
- [ ] `package.json` scripts:
```json
"api:types": "openapi-typescript ../backend/openapi.yaml -o src/api/schema.d.ts",
"typecheck": "tsc -b --noEmit",
"test": "vitest run"
```

### 4.2 Generate the API types
```bash
npm run api:types
```
**Check:** `src/api/schema.d.ts` exists and contains `"/api/v1/me"`.

### 4.3 Firebase (auth only) — `src/lib/firebase.ts`
```ts
import { initializeApp } from 'firebase/app';
import { getAuth } from 'firebase/auth';

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};
export const auth = getAuth(initializeApp(config));
```
No Firestore, Functions or Storage imports anywhere.

### 4.4 Typed API client — `src/api/client.ts`
```ts
import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './schema';
import { auth } from '../lib/firebase';

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    const token = await auth.currentUser?.getIdToken();
    if (token) request.headers.set('Authorization', `Bearer ${token}`);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: import.meta.env.VITE_API_URL });
api.use(authMiddleware);
```
(If the installed `openapi-fetch` version names the middleware argument differently, follow its docs; the behaviour must stay "attach the Firebase ID token to every request".)

### 4.5 Auth provider and `useMe`
- [ ] `src/lib/auth/AuthProvider.tsx`: wraps `onAuthStateChanged`; exposes `{ firebaseUser, loading, login(email, password), logout() }` using `signInWithEmailAndPassword` / `signOut`.
- [ ] `src/features/me/useMe.ts`: TanStack Query hook calling `api.GET('/api/v1/me')`; `enabled` only when a Firebase user exists; throws on error; `staleTime` 60 s.
- [ ] Map API errors (`code`) to a small `ApiError` type so UI can show friendly messages.

### 4.6 Routing shell
- [ ] `src/main.tsx`: `QueryClientProvider`, `AuthProvider`, `BrowserRouter`.
- [ ] Routes: `/` (public placeholder), `/login`, `/app` (dashboard layout; redirects to `/login` when signed out), `/app/me` (profile page).
- [ ] `src/pages/Login.tsx`: email + password form (React Hook Form + Zod), shows server/Firebase errors.
- [ ] `src/pages/Me.tsx`: shows `display_name`, `email`, `role`; if `role === null` shows "Your account is awaiting approval."
- [ ] Layout is mobile-first; add a visible "waking up" state when the first API call takes more than 3 s (free-tier cold starts).

### 4.7 Tests
- [ ] `src/pages/Login.test.tsx`: validation errors render; submit calls the login function (mock Firebase).
- [ ] `src/features/me/useMe.test.tsx`: renders loading → data using a mocked API client.
**Check:** `npm run typecheck && npm test && npm run build` all pass.

---

## Step 5 — CI (`.github/workflows/ci.yml`)

```yaml
name: ci
on: [push, pull_request]
jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env: { POSTGRES_PASSWORD: postgres, POSTGRES_DB: watan }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres" --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      SECRET_KEY: ci-secret
      DATABASE_URL: postgresql://postgres:postgres@localhost:5432/watan
      DB_SSL_REQUIRE: "False"
    defaults: { run: { working-directory: backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -r requirements/dev.txt
      - run: ruff check . && ruff format --check .
      - run: python manage.py makemigrations --check --dry-run
      - run: pytest
      - name: OpenAPI is up to date
        run: |
          python manage.py spectacular --file /tmp/openapi.yaml --validate
          diff -u openapi.yaml /tmp/openapi.yaml
  frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm, cache-dependency-path: frontend/package-lock.json }
      - run: npm ci
      - name: Generated API types are up to date
        run: |
          npm run api:types
          git diff --exit-code src/api/schema.d.ts
      - run: npm run typecheck
      - run: npm test
      - run: npm run build
```
**Check:** push to GitHub; both jobs go green.

---

## Step 6 — Staging connection and smoke test

- [ ] In `backend/.env` temporarily point `DATABASE_URL` to the **Neon pooled** URL with `DB_SSL_REQUIRE=True`; run `python manage.py migrate` against staging; confirm tables exist; run `GET /readyz` (200).
- [ ] Cold-start test: wait 6 minutes idle, then call `/readyz` and note the latency. Record it in `README.md` ("first request after idle: ~N s"). If the API retries once on a connection error, add that to `readyz` and to the frontend's "waking up" message.
- [ ] Put the Firebase service-account JSON into `FIREBASE_SERVICE_ACCOUNT_JSON` (single-line JSON) in `.env`, start the API, sign in from the React app, and open `/app/me`.
- [ ] R2 smoke test script `backend/scripts/r2_smoke.py`: upload a small object with a presigned PUT (using `curl`), HEAD it, generate a presigned GET, download it, delete it. Confirm CORS by performing the PUT from the browser dev tools at least once.
- [ ] Revert `.env` to local values (never commit staging credentials).

---

## Step 7 — README and handover

- [ ] `README.md`: prerequisites, `docker compose up -d`, backend setup/run/test commands, frontend setup/run/test commands, how to regenerate OpenAPI + TS types, environment variable table, and the cold-start measurement.
- [ ] Add a "Sprint 1 starts here" section pointing to `WATAN_LMS_V2_BLUEPRINT.md` section 13.

---

## Sprint 0 — Definition of Done

- [ ] `pytest` green; `ruff` clean; `makemigrations --check` clean.
- [ ] `backend/openapi.yaml` and `frontend/src/api/schema.d.ts` committed and CI confirms they are current.
- [ ] A real Firebase login in the React app shows `/app/me` data from Django on **staging Neon**.
- [ ] `/healthz` and `/readyz` work; cold-start latency measured and documented.
- [ ] R2 presigned PUT/GET verified; bucket is private; CORS locked to your origins.
- [ ] CI green on GitHub.
- [ ] No secrets in the repo (`git log -p | grep -i "private_key"` returns nothing).
