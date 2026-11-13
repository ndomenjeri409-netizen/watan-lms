# Watan LMS v2

Watan LMS v2 is a unit-aware learning management system: Django REST Framework and PostgreSQL on the backend, React and TypeScript on the frontend, Firebase Authentication, and private S3-compatible object storage. [`docs/MASTER_GUIDE.md`](docs/MASTER_GUIDE.md) is the authoritative architecture and delivery guide; [`docs/PROGRESS.md`](docs/PROGRESS.md) tracks current work.

## Run locally

Prerequisites: Python 3.12, Node.js 22, and Docker Desktop for local PostgreSQL/MinIO development. Follow `docs/MASTER_GUIDE.md` for hosted database and storage configuration.

1. Copy `backend/.env.example` to `backend/.env` and set local development values. Copy `frontend/.env.example` to `frontend/.env.local` and add the Firebase web app configuration. Never commit either file.
2. Start local PostgreSQL and MinIO: `docker compose up -d db minio`.
3. Install backend dependencies, migrate, and seed the approved unit list:

   ```powershell
   cd backend
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements/dev.txt
   python manage.py migrate
   python manage.py seed_units
   python manage.py runserver 8000
   ```

4. In a second terminal, install frontend dependencies and start Vite:

   ```powershell
   cd frontend
   npm ci
   npm run dev
   ```

5. Open the frontend at `http://localhost:3000`; the backend health endpoint is `http://localhost:8000/healthz`.

From the repository root, run `python scripts/check_docs.py`. Run backend checks from `backend`: `pytest`, `ruff check .`, `ruff format --check .`, and `python manage.py makemigrations --check --dry-run`. Run frontend checks from `frontend`: `npm run lint`, `npm run typecheck`, `npm test`, and `npm run build`.

## API types

Regenerate and validate the OpenAPI contract with `python manage.py spectacular --file openapi.yaml --validate` from `backend`, then run `npm run api:types` from `frontend`. Do not hand-edit `openapi.yaml` or `frontend/src/api/schema.d.ts`.

## Environment variables

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django signing key |
| `DATABASE_URL` | PostgreSQL connection URL |
| `DB_SSL_REQUIRE` | Require TLS for database connections |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Firebase Admin service-account JSON |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed browser origins |
| `STORAGE_ENDPOINT_URL`, `STORAGE_BUCKET` | Private object storage endpoint and bucket; legacy `B2_*` and `R2_*` environment names remain supported |
| `STORAGE_ACCESS_KEY_ID`, `STORAGE_SECRET_ACCESS_KEY` | Bucket-scoped object access credentials; legacy `B2_*` and `R2_*` environment names remain supported |
| `STORAGE_REGION` | Optional signing region; Backblaze B2 endpoint regions are detected from the endpoint hostname |
| `VITE_API_URL` | Django API base URL |
| `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_APP_ID` | Firebase browser app configuration |

## Multi-unit model

The business operates as one organization with business units as cost centres. Unit codes and names are maintained in [`docs/units.md`](docs/units.md); seed or refresh them idempotently with `python manage.py seed_units` from `backend`.

Access is granted through role assignments rather than a single account-wide role. Group-scoped roles (`SUPER_ADMIN`, `ADMIN`, `DIRECTOR`, `AUDITOR`) have no unit on the assignment; operational roles such as `UNIT_MANAGER`, `HOD`, `TEACHER`, and `CASHIER` are assigned to a unit. A `BURSAR` assignment may be unit-scoped or group-wide. Student access is derived from the linked Student record, not a role assignment. Group readers can view across units; director and auditor access is read-only. Unit-scoped API lists are restricted to assigned units and can accept `?unit=<unit-id>` to select one permitted unit.

Department, Program, Course, Enrollment, and TimetableSlot each carry a required business-unit relationship, with parent/child consistency enforced. Department assignments are backfilled from the approved mapping in `docs/department_unit_map.csv`.

Students may be registered without a portal account. Role assignments and records are scoped by business unit; see the master guide for authorization, academic, finance, and data-protection rules.

## Project status

Follow the ordered roadmap in [`docs/MASTER_GUIDE.md`](docs/MASTER_GUIDE.md) and check [`docs/PROGRESS.md`](docs/PROGRESS.md) for completed work and the next step. Historical plans are kept under `docs/archive/` and are superseded.

Step 5b offline student registration is complete. Step 6 authorization coverage is in progress; the PostgreSQL-only concurrent course-edit test still needs CI verification.
