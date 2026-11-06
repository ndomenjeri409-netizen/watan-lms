# Watan LMS v2

Watan LMS v2 is a Django REST API and React application using Firebase Authentication, PostgreSQL, and a private S3-compatible file bucket.

## Run locally

Prerequisites: Python 3.12, Node.js 22, Docker Desktop, and Neon CLI (for hosted database work).

1. Copy `backend/.env.example` to `backend/.env` and set a local secret key. Copy `frontend/.env.example` to `frontend/.env.local` and add the Firebase web app configuration.
2. Start local PostgreSQL and MinIO: `docker compose up -d`.
3. Install backend dependencies and migrate:

   ```powershell
   cd backend
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements/dev.txt
   python manage.py migrate
   python manage.py runserver
   ```

4. In a second terminal, install frontend dependencies and start Vite:

   ```powershell
   cd frontend
   npm ci
   npm run dev
   ```

5. Run checks with `pytest` and `ruff check .` from `backend`; from `frontend`, run `npm run typecheck`, `npm test`, and `npm run build`.

## API types

Regenerate the OpenAPI contract with `python manage.py spectacular --file openapi.yaml --validate` from `backend`, then run `npm run api:types` from `frontend`.

## Environment variables

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django signing key |
| `DATABASE_URL` | PostgreSQL connection URL |
| `DB_SSL_REQUIRE` | Require TLS for database connections |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Firebase Admin service-account JSON |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed browser origins |
| `R2_ENDPOINT_URL`, `R2_BUCKET` | Private object storage endpoint and bucket |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Bucket-scoped object access credentials |
| `VITE_API_URL` | Django API base URL |
| `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_APP_ID` | Firebase browser app configuration |

No staging cold-start measurement is available yet; record the measured first-request latency here after staging is reachable.

## Multi-unit model

The business operates as one organization with business units as cost centres. Unit codes and names are maintained in [`docs/units.md`](docs/units.md); seed or refresh them idempotently with `python manage.py seed_units` from `backend`.

Access is granted through role assignments rather than a single account-wide role. Group-scoped roles (`SUPER_ADMIN`, `ADMIN`, `DIRECTOR`, `AUDITOR`) have no unit on the assignment; operational roles such as `UNIT_MANAGER`, `HOD`, `TEACHER`, and `CASHIER` are assigned to a unit. A `BURSAR` assignment may be unit-scoped or group-wide. Student access is derived from the linked Student record, not a role assignment. Group readers can view across units; director and auditor access is read-only. Unit-scoped API lists are restricted to assigned units and can accept `?unit=<unit-id>` to select one permitted unit.

Departments belong to a unit. The Department unit migration is nullable for existing records so that legacy departments are not assigned to a unit without an approved mapping; new department records require a unit.

The authoritative, expanded role and finance model is in [`docs/MULTI_UNIT_AND_FINANCE_ADDENDUM.md`](docs/MULTI_UNIT_AND_FINANCE_ADDENDUM.md), which supersedes the earlier role list and finance-ledger description in the blueprint.

## Sprint 1 starts here

Continue with section 13 of `docs/WATAN_LMS_V2_BLUEPRINT.md`.
