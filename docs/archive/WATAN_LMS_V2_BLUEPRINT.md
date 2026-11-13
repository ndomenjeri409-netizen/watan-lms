> SUPERSEDED by MASTER_GUIDE.md; do not follow.

# Watan LMS v2 — Greenfield Blueprint

A new, standalone project built from zero, using everything v1 taught us. **Not** an in-place port of the Firestore app.

> **Superseded sections:** `docs/MULTI_UNIT_AND_FINANCE_ADDENDUM.md` is authoritative for the role list and finance ledger model; use it instead of the earlier role and finance descriptions in this blueprint.

- **Frontend:** React + TypeScript (Vite) — rebuilt cleanly, reusing v1's design language and content.
- **Backend:** Python — **Django + Django REST Framework**, a modular monolith.
- **Database:** Standard PostgreSQL on a free tier (recommendation in section 4; Supabase is *not* required).
- **Login:** Firebase Authentication only. No Firebase database, functions or storage.
- **Files:** real uploads in v2.0 (private S3-compatible object storage, Cloudflare R2 recommended; section 10.5).

**Decisions locked (Nov 2026):** M-Pesa integration is the **first release after launch**, not v2.0 · real file uploads **are** in v2.0. For the current roles and finance model, see the addendum linked above.

> Earlier I suggested FastAPI for an in-place migration. For a ground-up build, Django is the better fit: ORM, migrations, admin site, permissions, management commands and a mature ecosystem, which is what an LMS with ~40 tables, roles and finance workflows needs.

---

## 0. Rules for Copilot (read first)

1. Build **sprint by sprint** (section 13). Don't start a sprint until the previous sprint's "Done when" passes.
2. **Backend is the source of truth** for data, permissions and business rules. The frontend never decides access; it only hides UI.
3. **API contract is generated, not hand-written.** Backend emits `openapi.yaml`; frontend types are generated from it (section 9). Never hand-edit generated types.
4. **Every list endpoint is paginated and scoped by the caller's role** using `Model.objects.for_user(user)` (section 7). No endpoint may return unscoped rows.
5. **Money, grades and audit records are append-only** (section 6). Corrections are new rows that reverse old ones.
6. **No vendor lock-in:** only standard Postgres features. The database is swappable by changing `DATABASE_URL`.
7. Secrets only in environment variables / host secret stores. Never in the repo, never in `VITE_*`.
8. Every feature ships with tests (pytest + Django test client; Vitest/Playwright on the frontend for critical flows).

---

## 1. What v1 taught us

### Keep (these are your real assets)
| Asset | Where it lives in v1 | Use in v2 |
|---|---|---|
| Role model and permission rules | `src/lib/permissions.ts`, `firestore.rules` | The **specification** for v2 policies |
| Rules test suite | `tests/firestore.rules.test.ts` | Port to pytest as the authorization matrix |
| Domain model and status enums | `src/types/schema.ts` | Starting point for Django models |
| Public site content and branding direction | `src/content/*`, `docs/PUBLIC_BRANDING_BLACK_WHITE_GOLD_PLAN.md` | Carry over copy, layout and the black/white/gold identity |
| Student-portal UI findings | `docs/Phase9_Student_Portal_UI_Audit.md` | Backlog of known UX problems to fix by design |
| Assistant intents, knowledge base, eval questions | `workers/assistant/*`, `eval/questions.json` | Port into the v2 `assistant` app; keep the eval harness |
| QR attendance idea | `StudentQrAttendanceCheckin.tsx`, `attendanceQrTokens` | Keep and harden |

### Change
| v1 problem | v2 answer |
|---|---|
| No backend; 1,534 lines of security rules are the only guard | Real API with tested policies |
| Client-side transactions and batches (22 + 8) | Server-side DB transactions |
| Duplicate/competing types (`schema.ts` vs `index.ts`), duplicated `ServiceError` classes | One generated API contract |
| Embedded arrays (`attendance.records`, `messages`) | Proper child tables |
| Balances derived ad hoc; `financialLedger` never populated | Ledger is the source of truth |
| Data fetched by chatty per-component Firestore queries | Paginated, filtered, server-aggregated endpoints |
| Roles read from a user doc editable under rules | Roles managed only by the backend |
| Cloud Functions blocked by Spark plan | Normal backend code, no Blaze dependency |
| Files are pasted public URLs | Real file storage with signed URLs (optional, section 10) |

### Drop
Firestore SDK, `firestore.rules`, Firebase Functions, client-side permission enforcement as a security layer, the secondary-Firebase-app provisioning hack, direct DB access from the browser.

---

## 2. Design principles

1. **Role-first UX**: each role lands on "what needs my attention today", not a generic menu.
2. **One source of truth per fact** (a balance, an enrollment status, a grade).
3. **Append-only where trust matters** (payments, grades, audit).
4. **Boring, standard tech** that you can learn and hire for.
5. **Free-tier friendly, upgrade-ready**: everything works on free tiers; nothing blocks moving to paid hosting later.
6. **Mobile-first, low-bandwidth**: most students and teachers are on phones with costly data.

---

## 3. Stack decisions

| Layer | Choice | Why |
|---|---|---|
| Backend framework | Django 5 + Django REST Framework | Batteries included; great for relational, role-heavy systems; strong skill investment |
| API schema | `drf-spectacular` (OpenAPI 3) | Generates the contract used by the frontend |
| Filtering/pagination | `django-filter`, DRF pagination | Replaces v1's `where/orderBy/limit` constraint objects |
| Auth | Firebase Auth + custom DRF authentication class (`firebase-admin`) | Keeps your login; no password handling in Django |
| DB access | Django ORM + migrations | Single, versioned schema |
| Background jobs | A Postgres-backed queue (e.g. `procrastinate` or `django-q2` with ORM broker) | No Redis to host |
| Audit history | `django-simple-history` or custom `AuditLog` | Who changed what |
| Config | `django-environ` / `dj-database-url` | 12-factor settings |
| Serving | `gunicorn` + `whitenoise` in a Docker image | Runs on any container host |
| Frontend | React 19 + TypeScript + Vite + Tailwind v4 (already your stack) | Keep what works |
| Frontend data | **TanStack Query** + generated typed client (`openapi-typescript` + `openapi-fetch`) | Caching, refetching, optimistic updates; replaces hand-rolled polling |
| Forms/validation | React Hook Form + Zod | Consistent forms |
| Tests | pytest-django, factory_boy; Vitest; Playwright for critical flows | |
| CI | GitHub Actions | Lint, tests, OpenAPI drift check, weekly DB backup |

---

## 4. Database: Supabase limits and free alternatives

### Why Supabase free is risky for this system
Supabase Free gives 500 MB of database and 1 GB of file storage per project, and **pauses projects after about a week of inactivity** (verify at supabase.com/pricing). A school system goes quiet during holidays, and a paused database means the app is simply down until someone restores it. Also, you would use only its Postgres, not its extras, because Django talks to the database directly.

### Options (checked Nov 2026 from public pricing pages; **re-verify before committing**)
| Option | Free tier (approx.) | Fit for Django | Main catch |
|---|---|---|---|
| **Neon** | 0.5 GB per project, 100 CU-hours/month, compute scales to zero after 5 minutes idle | Excellent (plain Postgres) | First query after idle has a cold start of a few seconds; compute suspends if the monthly CU-hours are used up |
| **Supabase** | 500 MB, pauses after ~1 week idle | Excellent (plain Postgres) | Pausing; two active projects max |
| **Aiven (free Postgres)** | 1 CPU, 1 GB RAM, 1 GB disk, no time limit | Excellent (plain Postgres) | Small; check its current idle/power-off behaviour |
| **Prisma Postgres** | ~1 GB storage, ~200k operations/month | Works as plain Postgres | Operation quota can be hit by chatty ORM usage |
| **CockroachDB (Basic)** | ~10 GiB, 50M request units/month | Risky: Postgres-*compatible*, not Postgres; Django needs a third-party backend | Features/behaviour differ; not recommended for a first Django project |
| Turso / Cloudflare D1 | SQLite-style, several GB | Not a good fit for Django's finance-grade relational workload | Different SQL dialect/limits |

### Recommendation
1. **Primary: Neon Free.** Real Postgres, does not get paused for inactivity (it suspends and wakes automatically), roomy enough for a small institute if files stay outside the DB and logs are pruned.
2. **Fallback: Aiven Free** (bigger disk, always-on style) **or Supabase Free** with a daily keep-alive.
3. **Upgrade path:** when the institute can pay, move to a small paid Postgres. Because you only use standard Postgres, this is `pg_dump` → restore → change `DATABASE_URL`.

### Portability rules (so you are never trapped)
- No Supabase-specific or Neon-specific APIs in code (no `supabase-js`, no RLS-dependent logic, no vendor SDKs).
- Only Django ORM and standard SQL features. Extensions limited to commonly available ones (`pg_trgm`, `unaccent`, `citext`).
- Always connect via `DATABASE_URL`.
- Cold-start tolerance: the API retries the first DB connection once and the UI shows a friendly "waking up" state.
- Behind a connection pooler (PgBouncer in transaction mode), set `DISABLE_SERVER_SIDE_CURSORS = True`.

```python
# config/settings/base.py
import dj_database_url
DATABASES = {"default": dj_database_url.config(env="DATABASE_URL", conn_max_age=0, ssl_require=True)}
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True   # required behind transaction poolers
```

### Size budget
Keep the DB small: store files outside Postgres, prune `audit_logs`/`chat_messages` by retention policy, and monitor `pg_database_size`. Alert at 70% of the cap.

---

## 5. Architecture

```
                       ┌─────────────────────────────┐
  Browser / PWA  ───▶  │  React SPA (Vite, TS)       │  static hosting (Firebase Hosting or Cloudflare Pages)
                       └──────────────┬──────────────┘
                 Firebase Auth login  │  Bearer ID token
                                      ▼
                       ┌─────────────────────────────┐
                       │  Django + DRF API           │  container host (free tier; verify terms)
                       │  - FirebaseAuthentication   │
                       │  - policies + scoped QS     │
                       │  - services (transactions)  │
                       │  - OpenAPI schema           │
                       └──────┬───────────┬──────────┘
                              │           │ enqueue
                              ▼           ▼
                   PostgreSQL (Neon)   Job worker (same image, 2nd process or cron)
                                          │
                       Email / SMS / WhatsApp / M-Pesa / object storage (optional)
```

**Internal structure — a modular monolith.** One deployable, many Django apps with clear boundaries:

```
backend/
  config/                 # settings (base/dev/prod), urls, asgi/wsgi
  apps/
    accounts/             # User (firebase_uid, role), invites, role scopes
    org/                  # departments, programs, academic periods, campuses, settings
    academics/            # courses, modules, units, lessons, materials
    people/               # students, staff profiles, guardians
    enrollment/           # applications, enrollments, course access
    scheduling/           # classes, timetable slots, rooms, clash detection
    attendance/           # sessions, records, QR tokens, check-ins
    assessment/           # assessments, exams, submissions, grades, gradebook
    finance/              # fee structures, invoices, ledger, payments, refunds, M-Pesa
    comms/                # announcements, notifications, templates, delivery log
    assistant/            # knowledge base, chat, appointments, handoffs, WhatsApp
    cms/                  # public pages, blog, FAQ
    files/                # StoredFile, signed upload/download, quotas, cleanup
    reports/              # aggregates, exports, scheduled reports
    audit/                # audit log
  common/                 # base models, permissions, pagination, money, errors
  tests/
frontend/
  src/
    api/                  # generated schema + client (never hand-edited)
    features/             # one folder per domain (courses, students, finance, ...)
    components/           # design-system primitives
    routes/               # public + dashboard layouts, role-based routing
    lib/                  # firebase auth wrapper, utils
```

**Hosting (verify current terms):** frontend on Firebase Hosting or Cloudflare Pages (static, free); API on a container host with a free tier (for example Render, Koyeb or Fly.io; free instances usually sleep when idle); DB on Neon. Keep API and DB in the same region to avoid slow cross-region ORM calls; measure latency from Kenya, since these free tiers may not have a nearby region.

**Environments:** `local` (Docker Compose with Postgres) → `staging` (own free DB project) → `production`. Never test against production data.

---

## 6. Domain model (improvements over Firestore)

General conventions: UUID primary keys, `created_at/updated_at`, real **foreign keys**, `legacy_id` (nullable, unique) on imported tables for traceability to v1, soft-delete (`is_active`/`archived_at`) instead of hard delete for people and academic records.

| Area | Key entities | Design notes |
|---|---|---|
| Accounts | `User(firebase_uid, email, role, is_active)`, `RoleScope(user, department/class)` | Roles live only here. HOD may hold several departments. |
| Org | `Campus`, `Department`, `Program`, `AcademicPeriod` | `Campus` is optional now but makes multi-campus possible later. |
| Academics | `Course`, `CourseModule`, `Unit`, `Lesson`, `Material` | `Material` has `kind` and `url` or stored file. |
| People | `Student`, `StaffProfile`, `Guardian` | Registration number generated by a DB-safe sequence per department/year. |
| Enrollment | `Application`, `Enrollment(state machine)`, `CourseAccess` | Statuses: `PENDING → APPROVED → ACTIVE → COMPLETED` or `REJECTED/CANCELLED`. Transitions live in one service function. |
| Scheduling | `ClassGroup`, `TimetableSlot`, `Room` | Clash detection (teacher, room, group) enforced in service + exclusion constraint where practical. |
| Attendance | `AttendanceSession`, `AttendanceRecord` (**one row per student**), `QrToken`, `CheckIn` | Replaces v1's embedded `records` array. Unique `(session, student)`. |
| Assessment | `Assessment`, `Exam`, `Submission`, `Grade`, `GradeRevision` | Grade workflow `DRAFT → SUBMITTED → APPROVED → PUBLISHED`; edits create revisions, never overwrite. |
| Finance | `FeeStructure/Item`, `Invoice`, `LedgerEntry`, `Payment`, `Refund`, `Adjustment` | **Ledger is the source of truth.** Balance = `SUM(ledger.amount)`. |
| Comms | `Announcement`, `Notification`, `MessageTemplate`, `DeliveryAttempt` | Delivery log supports retries and "did they get it?". |
| Assistant | `KnowledgeEntry`, `ChatSession`, `ChatMessage`, `Handoff`, `Appointment`, `AppointmentSlot`, `Gap` | Retention job prunes old chats. |
| CMS | `Page`, `BlogPost`, `FaqEntry` | Staff edit public content without deploys. |
| Audit | `AuditLog(actor, action, object, before, after, at)` | Written in the same transaction as the change. |
| Files | `StoredFile(purpose, object_key, size, status)` | Visibility derives from the owning object; see section 10.5. |

### Append-only finance ledger (pattern)

```python
class LedgerEntry(models.Model):
    class Type(models.TextChoices):
        INVOICE = "INVOICE"; PAYMENT = "PAYMENT"; ADJUSTMENT = "ADJUSTMENT"; REFUND = "REFUND"; REVERSAL = "REVERSAL"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="ledger")
    invoice = models.ForeignKey("finance.Invoice", null=True, on_delete=models.PROTECT, related_name="ledger")
    entry_type = models.CharField(max_length=12, choices=Type)
    amount = models.DecimalField(max_digits=12, decimal_places=2)   # charges +, credits −
    reverses = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    reference = models.CharField(max_length=64, blank=True)         # e.g. M-Pesa code
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["entry_type", "reference"],
                       condition=~models.Q(reference=""), name="uniq_ledger_reference")]  # idempotent payments

    def save(self, *a, **kw):
        if not self._state.adding: raise ValueError("Ledger entries are append-only")
        super().save(*a, **kw)
    def delete(self, *a, **kw): raise ValueError("Ledger entries are append-only")
```
Also add a migration with a DB trigger that rejects `UPDATE`/`DELETE` on this table, so even raw SQL can't tamper with it. Same pattern for `audit_log` and `grade_revision`.

---

## 7. Roles and authorization

Roles (**final**): `SUPER_ADMIN`, `ADMIN`, `DIRECTOR`, `HOD`, `TEACHER`, `BURSAR`, `STUDENT`. v1's `FINANCE` is replaced by **BURSAR** (the v1 import maps `FINANCE → BURSAR`); **DIRECTOR** is new and read-focused (dashboards, reports, drill-downs; no edits to academic or finance records).

### Three layers, all server-side
1. **Role gate** (DRF permission class): can this role use this endpoint at all?
2. **Row scope** (`for_user` on the queryset): which rows may this user *see*? Applied to every list/detail query, so a client cannot widen it.
3. **Object/action rule** (policy function): may this user perform *this action on this object* (e.g. TEACHER grading only their own class's submissions)?

```python
# common/scoping.py
class ScopedQuerySet(models.QuerySet):
    def for_user(self, user):
        raise NotImplementedError

# finance/models.py
class InvoiceQuerySet(ScopedQuerySet):
    def for_user(self, u):
        if u.role in {"SUPER_ADMIN", "ADMIN", "BURSAR", "DIRECTOR"}: return self
        if u.role == "STUDENT": return self.filter(student_id=u.student_id)
        if u.role == "HOD":     return self.filter(student__department__in=u.department_ids)
        return self.none()
```
Base viewset: `get_queryset()` always returns `Model.objects.for_user(request.user)`. A CI test fails the build if any `ModelViewSet` doesn't.

### Authorization test matrix
Port `tests/firestore.rules.test.ts` into `tests/test_authorization.py`: parametrized `(role, resource, action, fixture) → expected status`. One test user per role plus two HODs in different departments and two students. This suite is the safety net for every later change.

---

## 8. Authentication (Firebase stays for login)

**Flow:** React signs in with Firebase → gets an ID token → sends `Authorization: Bearer <token>` → Django verifies the token → loads the local `User` → applies role/scope.

```python
# accounts/authentication.py
import firebase_admin
from firebase_admin import auth as fb_auth, credentials
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

firebase_admin.initialize_app(credentials.Certificate(json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)))

class FirebaseAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        try:
            decoded = fb_auth.verify_id_token(header[7:])
        except Exception:
            raise AuthenticationFailed("Invalid or expired session")
        user, _ = User.objects.get_or_create(
            firebase_uid=decoded["uid"], defaults={"email": decoded.get("email", ""), "role": None})
        if not user.is_active:
            raise AuthenticationFailed("Account disabled")
        return (user, decoded)
```

- Users with `role = None` can authenticate but only reach `GET /me` and the "awaiting approval" screen.
- **Invites and provisioning are server-side:** staff create a student/teacher in the dashboard; the backend creates the Firebase user with the Admin SDK, creates the local `User`, and the frontend triggers Firebase's password-reset email as the invite.
- **Role changes** only via `PATCH /users/{id}/role` (admin policy; SUPER_ADMIN rules enforced).
- Verify token revocation for sensitive actions (`check_revoked=True` on role-changing and money endpoints).
- Optional later: replace Firebase with Django-native auth if you ever want zero external dependency; keep the authentication class boundary so this is a swap, not a rewrite.

---

## 9. API design and the contract pipeline

- REST, versioned under `/api/v1/`. Resource-oriented URLs; **action endpoints** for workflows (`POST /enrollments/{id}/approve`, `POST /grades/{id}/publish`, `POST /payments`).
- Standard list params: `?page`, `?page_size` (max 100), `?search`, `?ordering`, plus explicit `django-filter` fields. No arbitrary field filtering.
- Errors: `{ "code": "PERMISSION_DENIED|NOT_FOUND|VALIDATION|CONFLICT", "message": "...", "fields": {...} }`.
- Idempotency: payment/booking endpoints accept an `Idempotency-Key` header.
- Conditional requests (`ETag`) on read-heavy lists to save mobile data.
- Money serialized as **strings** ("1500.00") in the API and parsed explicitly in the UI (avoids float errors); a tiny `Money` helper lives in `frontend/src/lib/money.ts`.

### Contract pipeline (the "single source of truth" fix)
```
Django serializers/viewsets
   └─ drf-spectacular ──▶ backend/openapi.yaml  (committed)
                              └─ openapi-typescript ──▶ frontend/src/api/schema.d.ts (generated)
                                                          └─ openapi-fetch typed client + TanStack Query hooks
```
CI step: regenerate `openapi.yaml`; fail if it differs from the committed file; regenerate TS types; run `tsc`. Any backend change that would break the UI breaks the build.

---

## 10. Data pipeline (how data and work flow)

### 10.1 Request path (synchronous)
`React → TanStack Query → typed API client → Django (authenticate → role gate → scoped queryset → service layer → DB transaction) → serializer → JSON`.

- **Service layer** (`apps/<app>/services.py`): all multi-step business operations (enroll, approve grade, record payment, issue invoice) live here, wrapped in `transaction.atomic()` with `select_for_update()` where races matter. Views stay thin.
- **Queries:** `select_related/prefetch_related` by default; no N+1 (add `django-debug-toolbar`/query-count assertions in tests).
- **Aggregates server-side:** dashboard numbers come from SQL aggregates (`/reports/overview`), not from downloading lists.

### 10.2 Background path (asynchronous)
Enqueue to the Postgres-backed queue for: sending email/SMS/WhatsApp, PDF generation (transcripts, receipts, certificates), report exports, bulk imports, fee reminders, retention cleanup, nightly aggregates. Jobs are idempotent and retried with backoff. Locally and in CI they run eagerly.

On free hosting where a second always-on process isn't available, run the worker as a **scheduled job** (GitHub Actions cron or the host's cron) invoking `python manage.py run_due_jobs`.

### 10.3 Events inside the monolith
Use explicit domain events (a small `publish("enrollment.approved", payload)` helper) instead of hidden signals. Handlers: create `CourseAccess`, write `AuditLog`, enqueue the notification. This replaces v1's missing Cloud Function triggers and makes flows readable.

### 10.4 Real-time needs
Start with TanStack Query refetch-on-focus + short intervals for live screens (attendance, assistant handoffs). If a screen truly needs push, add **Server-Sent Events** later. No WebSocket infrastructure in v1.

### 10.5 Files (real uploads in v2.0)

**Storage:** private S3-compatible bucket. Recommended: **Cloudflare R2**, whose free allowance (checked Nov 2026; re-verify) is 10 GB-month of storage, 1 million write/list operations and 10 million read operations per month, with free egress. Storage is the limit you hit first. Videos stay as external links (for example unlisted YouTube) so the 10 GB goes to documents and images. Check whether account signup requires a payment method.

**Rule: files never pass through Django and the bucket is never public.** Django only authorizes and issues short-lived signed URLs.

```
Upload:   POST /api/v1/files/uploads        {purpose, filename, content_type, size}
            → policy check (role, purpose, size, type) → creates StoredFile(status=PENDING)
            → returns {file_id, upload_url (presigned PUT, ~5 min), headers}
          Browser PUTs the bytes straight to the bucket
          POST /api/v1/files/{id}/complete
            → Django HEADs the object, verifies size/type/etag → status=READY (else deletes it, 422)
Download: GET /api/v1/files/{id}/download-url
            → authorize via the OWNING object's policy (course material, submission, receipt…) → presigned GET (~5 min)
```

**`files` app model (sketch):** `StoredFile(id, purpose, owner_user, object_key, original_name, content_type, size_bytes, sha256?, status[PENDING|READY|DELETED], created_at)`; domain tables reference it by FK (`Material.file`, `Submission.file`, `Student.photo`, `Receipt.file`). A file's visibility is **derived from the object that owns it**, never from the file row alone.

**Upload policy table (adjust numbers):**
| Purpose | Who may upload | Types | Max size |
|---|---|---|---|
| `material` | TEACHER (own course), HOD, ADMIN | pdf, docx, pptx, xlsx, images, zip | 25 MB |
| `submission` | STUDENT (own enrollment) | pdf, docx, pptx, xlsx, images, zip | 10 MB |
| `profile_photo` / `cover_image` | self / HOD, ADMIN | jpg, png, webp | 3 MB (compress client-side) |
| `document` (admissions) | applicant / STUDENT | pdf, images | 5 MB |
| `generated` (receipts, transcripts, certificates) | system jobs only | pdf | n/a |

**Hardening checklist:**
- R2 does not support S3 POST-policy uploads, so size cannot be enforced by the signature. Enforce at `complete` (HEAD → compare `ContentLength`, delete if too large) and set a hard max in a bucket lifecycle/cleanup job.
- Validate extension **and** content type; sniff the first bytes (`python-magic`/`filetype`) in `complete`; store under random keys (`purpose/yyyy/mm/uuid`), never the user's filename.
- Never serve user files from your own domain inline; force `Content-Disposition: attachment` for non-images.
- Optional malware scan as a background job before status becomes `READY` for student-visible files (for example a ClamAV container if your host allows, or a scanning API).
- Orphan cleanup job: delete `PENDING` rows and objects older than 24 hours; delete objects whose owner row was removed.
- Quota guard: a nightly job sums `size_bytes`; alert at 70% and block new uploads at 95% of the budget. Per-user and per-purpose rate limits.
- Bucket CORS: allow `PUT`/`GET` only from your frontend origins; bucket has no public access and no public dev URL.
- Client: compress images before upload, show progress, resume/retry once, and handle URL expiry by requesting a fresh URL.

```python
# files/storage.py  (boto3 against R2)
import boto3
from django.conf import settings

_s3 = boto3.client(
    "s3", endpoint_url=settings.R2_ENDPOINT_URL, region_name="auto",
    aws_access_key_id=settings.R2_ACCESS_KEY_ID, aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
)

def presign_put(key: str, content_type: str, expires=300) -> str:
    return _s3.generate_presigned_url("put_object",
        Params={"Bucket": settings.R2_BUCKET, "Key": key, "ContentType": content_type}, ExpiresIn=expires)

def presign_get(key: str, filename: str, expires=300) -> str:
    return _s3.generate_presigned_url("get_object",
        Params={"Bucket": settings.R2_BUCKET, "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{filename}"'}, ExpiresIn=expires)

def head(key: str): return _s3.head_object(Bucket=settings.R2_BUCKET, Key=key)
def delete(key: str): _s3.delete_object(Bucket=settings.R2_BUCKET, Key=key)
```
Keep this behind a small `Storage` interface so the provider (R2, S3, Supabase Storage, MinIO locally) is swappable. Local dev uses MinIO in Docker Compose.

### 10.6 Audit, observability, backups
- `AuditLog` row written in the same transaction as every important change (who, what, before/after).
- Structured logs + Sentry free tier for errors; `/healthz` and `/readyz` endpoints.
- **Backups:** weekly (daily during term) `pg_dump` via GitHub Actions to private storage. Do not rely on a free tier's built-in recovery for finance data.
- Retention job prunes chat messages and old logs to protect the DB size budget.

---

## 11. UX blueprint

### 11.1 Principles
Role-first home screens · one primary action per screen · server-side search, filter and pagination everywhere · fast on mobile and slow networks (skeletons, optimistic updates, small bundles, route-level code splitting) · errors that explain what to do next · accessible by default (keyboard, contrast, labels) · English + Swahili ready (i18n from day one).

### 11.2 Global shell (dashboard)
- Left nav filtered by role; collapsible; bottom tab bar on mobile.
- **Command palette (Ctrl/Cmd+K):** jump to a student, course, invoice, or action ("record payment").
- **Global search** across students, courses, invoices (server-side).
- **Notification bell + inbox** (announcements, approvals waiting, fee reminders).
- Breadcrumbs, consistent table component (sticky header, column chooser, saved filters, CSV export, bulk actions), consistent drawer-based create/edit forms.

### 11.3 Role home screens ("what needs my attention")
| Role | Home shows | Key tools |
|---|---|---|
| **Student** | Today's timetable, next assessment due, fee balance (+ "Pay with M-Pesa" from v2.1), new announcements, attendance %, grades | Course page with materials, submit work (link/upload), printable receipts, certificate download |
| **Teacher** | Today's classes, one-tap attendance (QR or list), submissions waiting to be graded, at-risk students | Gradebook grid with keyboard entry, announcements to a class, material upload |
| **HOD** | Department KPIs, pending enrollments and grade approvals, teacher load | Approve/reject queues, timetable view, department reports |
| **Bursar** | Collections today/this week, overdue invoices (aging), unreconciled payments | Record/verify payments, issue invoices, refunds with approval, statements, reconciliation |
| **Director** | Executive dashboard: enrollment, revenue vs target, attendance and pass-rate trends | Read-only drill-downs, scheduled report emails |
| **Admin / Super Admin** | System health, pending users, audit highlights | User/role management, settings, content (CMS), data imports |

### 11.4 Key flows to design carefully
1. **Admissions funnel:** public course page → apply → documents → interview/appointment booking → offer → payment of fee → auto-enrolment.
2. **Attendance:** teacher opens a session → shows rotating QR → students scan → live count; **works offline** (queue check-ins locally and sync).
3. **Grading:** import/enter marks in a grid → submit → HOD approves → publish → student notified.
4. **Fees:** invoice → student pays → Bursar records/verifies the payment (v2.0: manual M-Pesa code entry; v2.1: STK push with callback auto-posting to the ledger) → receipt generated and sent.
5. **Onboarding:** invite email → set password → profile completion → role-based welcome tour.

### 11.5 Public site
Keep v1's pages (Home, About, Courses, Departments, Instructors, Admissions, Pricing, Blog, FAQ, Contact, Features) but make them **CMS-driven**, SEO-friendly (server-rendered or pre-rendered meta, sitemap, structured data for courses), fast (image resizing, lazy loading) and conversion-focused (clear "Apply" and "Book a visit" calls to action). Embed the assistant widget. Carry over the black/white/gold identity into **design tokens** shared by public site and dashboard.

### 11.6 Design system
Tokens (colour, spacing, type, radius, elevation) in Tailwind theme; primitives: Button, Input, Select, DataTable, Drawer, Modal, Toast, Empty state, Skeleton, Stat card, Badge; each with loading/empty/error states documented in Storybook (optional).

### 11.7 PWA and low-bandwidth
Installable PWA, offline shell, background sync for attendance and drafts, compressed responses, `ETag`s, image `srcset`, lazy routes.

---

## 12. Opportunities — how this becomes a "super system"

Ranked by value for a Kenyan training institute vs effort. "Verify" = check provider terms/fees before committing.

| # | Opportunity | Why it matters | Effort | Notes |
|---|---|---|---|---|
| 1 | **M-Pesa (Daraja) STK push + automatic reconciliation** — *decided: first release after launch (v2.1)* | Fees are the lifeblood; removes manual matching; v1 already lists `MPESA` as a method | M | Needs a Safaricom developer account and a paybill/till; callbacks post idempotently to the ledger (verify requirements) |
| 2 | **Admissions and applications pipeline** | Turns your website into a lead-to-enrolment funnel | M | Reuses appointments + documents + payment |
| 3 | **Fee reminders and dunning** (SMS/WhatsApp/email) | Reduces arrears with zero staff time | S–M | SMS gateway costs money (verify); email/WhatsApp cheaper |
| 4 | **Certificates and transcripts with QR verification** | Credibility; employers verify online | S–M | Public verify page by signed certificate ID |
| 5 | **Unified WhatsApp + web assistant inside Django** | One brain for FAQs, bookings, handoffs; keeps your tested intents/eval harness | M | Port from `workers/assistant`; keep Gemini behind an interface and a daily budget guard |
| 6 | **Early-warning dashboard** (attendance + grades + arrears → "at risk") | Retention and results | S (rules) → M (model) | Start with transparent rules; add ML only if data justifies |
| 7 | **Gradebook with weighting, moderation and transcripts** | Core academic credibility | M | Already modelled via grade revisions |
| 8 | **Timetable clash detection and room/teacher load view** | Saves admin hours | S–M | |
| 9 | **Quizzes with auto-marking and course progress tracking** | Makes it a real LMS, not just a records system | M | Video via unlisted external links keeps hosting cost at zero |
| 10 | **Parent/guardian read-only portal and sponsor statements** | Useful for fee-paying guardians/sponsors | S–M | Separate `GUARDIAN` role scoped to linked students |
| 11 | **Scheduled executive reports** (weekly PDF/email to the Director) | Management visibility | S | Uses job queue + report templates |
| 12 | **AI helpers with human-in-the-loop** (draft announcements, summarize a student's record, draft feedback comments) | Time saving | S–M | Drafts only; staff approve; never auto-send grades/finance |
| 13 | **Multi-campus readiness** | Growth | S now, L later | `Campus` FK on key tables from day one |
| 14 | **Public API + webhooks** | Integrations (accounting, HR) | M | Token auth + rate limits |

**Data protection:** you hold student and financial data. Plan consent records, role-limited exports, retention rules and an audit trail from day one; have the setup reviewed against Kenya's Data Protection Act (2019) by someone qualified.

---

## 13. Build roadmap (sprint plan for Copilot)

Each sprint ends with: tests green, OpenAPI regenerated, frontend types regenerated, a deployable staging build.

### Sprint 0 — Foundation
- [ ] Monorepo (`backend/`, `frontend/`), Docker Compose (Django + Postgres), pre-commit (ruff, black, eslint, prettier), GitHub Actions (lint, tests, OpenAPI drift check).
- [ ] Django project `config/` with split settings, `DATABASE_URL`, CORS, DRF defaults, pagination, error handler, `/healthz`.
- [ ] Neon project created; staging connected; `DISABLE_SERVER_SIDE_CURSORS` set.
- [ ] Cloudflare R2 bucket (private) + scoped API token + CORS created; MinIO added to Docker Compose; `Storage` interface stub in `files/storage.py`.
- [ ] `common/`: base models, `ScopedQuerySet`, `Money`, error format.
- [ ] Frontend: Vite + TS + Tailwind tokens, router (public + dashboard layouts), TanStack Query, generated API client pipeline, Firebase Auth wrapper.
- **Done when:** a logged-in user (Firebase) calls `GET /api/v1/me` from the React app and sees their profile via the typed client.

### Sprint 1 — Identity, org, authorization
- [x] `accounts`: `User`, roles, `RoleScope`, `FirebaseAuthentication`, invites (Admin SDK), role-change endpoint.
- [x] `org`: campuses, departments, programs, academic periods.
- [x] `audit`: `AuditLog` + helper used by services.
- [x] Authorization test matrix scaffold; port the first slice of `firestore.rules.test.ts` (users, org).
- [x] Frontend: login, "awaiting approval", role-based nav, Users and Departments screens.
- **Done when:** each role sees only its allowed nav and data; matrix tests pass.

### Sprint 2 — Academics
- [ ] `academics` models/API (courses, modules, units, lessons, materials); HOD scoping; archive instead of delete.
- [ ] Frontend: course catalog, course editor, cover-image picker (carry over v1 design), material links.
- [ ] **`files` app:** `StoredFile`, upload/complete/download-url endpoints, policy table, orphan-cleanup and quota jobs; used first by course materials and cover images.
- [ ] Public CMS foundations (`cms`): pages, FAQ, blog; public read endpoints.
- **Done when:** staff manage courses; public site lists live courses from the API.

### Sprint 3 — People and enrollment
- [ ] `people`: students, staff profiles, registration number service (atomic per department/year).
- [ ] `enrollment`: applications, enrollment state machine service, course-access projection via domain event.
- [ ] Student provisioning flow (server-side Firebase user creation + invite).
- [ ] Frontend: Students list (server-side search/filter/pagination), student profile, enrollment queues.
- **Done when:** apply → approve → student gains course access, fully audited.

### Sprint 4 — Scheduling and attendance
- [ ] `scheduling`: classes, timetable slots, clash detection.
- [ ] `attendance`: sessions, per-student records, QR tokens, check-in endpoint (unique per session/student), offline queue on the PWA.
- [ ] Frontend: timetable views, teacher attendance screen, student QR scan.
- **Done when:** a teacher runs a QR attendance session and records appear live; double check-in is rejected.

### Sprint 5 — Assessment and grading
- [ ] `assessment`: assessments, exams, submissions, grade workflow with revisions, gradebook endpoint.
- [ ] Student submissions use real uploads (`purpose=submission`) with size/type limits and teacher-only download links.
- [ ] Frontend: submissions queue, gradebook grid, approval and publish screens, student grades view.
- [ ] Transcript PDF job.
- **Done when:** a grade goes DRAFT → PUBLISHED with HOD approval and shows on the student transcript.

### Sprint 6 — Finance
- [ ] `finance`: fee structures, invoices, **ledger**, payments (idempotent), adjustments (including voids as reversals), refunds with approval.
- [ ] **Manual M-Pesa entry at launch:** Bursar records the M-Pesa transaction code as `reference` (unique, so duplicates are rejected). The ledger/payment schema is already shaped for Daraja callbacks in v2.1.
- [ ] Balances/aging via SQL aggregates; receipts PDF (stored as `generated` files); statements.
- [ ] Frontend: Bursar workspace, student fee view, print receipt.
- [ ] Verify: sums in ledger equal v1 balances for imported data (section 14).
- **Done when:** record → reverse → refund flows balance to the cent and tests prove append-only behaviour.

### Sprint 7 — Communications, reports, public site polish
- [ ] `comms`: announcements, notifications inbox, templates, delivery log; email sending.
- [ ] `reports`: overview aggregates, exports, Director dashboard, scheduled email.
- [ ] Public site finished: admissions funnel entry, SEO, performance pass.
- **Done when:** each role's home screen from section 11.3 works with real data.

### Sprint 8 — Assistant and appointments
- [ ] `assistant`: knowledge entries, chat sessions/messages, appointment slots and booking (transactional), handoffs, retention job.
- [ ] Port intents, prompts and eval harness from `workers/assistant`; WhatsApp webhook endpoint with signature verification; Turnstile on the widget.
- [ ] Gemini behind a provider interface with a daily budget guard.
- **Done when:** the eval questions pass at or above v1's results; booking works end to end.

### Sprint 9 — Hardening and launch
- [ ] Security review (authz matrix complete, rate limiting, secure headers, `check_revoked` on sensitive actions, secrets audit).
- [ ] Backups (GitHub Actions `pg_dump`), monitoring (Sentry), load test on the free tiers, cold-start UX.
- [ ] v1 data import rehearsal ×2, then cutover (section 14).
- **Done when:** go-live checklist (Appendix B) is fully ticked.

### After launch
M-Pesa integration, admissions pipeline, fee reminders, certificates with QR verification (opportunities 1–4), then early-warning analytics.

---

## 14. One-time import from v1 (Firestore → v2)

1. Export all v1 collections with the Firebase Admin SDK to JSON (spread over days if you hit Spark read limits).
2. Write `manage.py import_v1 --from <dir> --dry-run` as **idempotent** upserts keyed by `legacy_id`; load in dependency order: org → users → people → academics → enrollment → scheduling → attendance → assessment → finance.
3. Map v1 `users.uid` to `User.firebase_uid`, so existing logins keep working unchanged.
4. Convert v1's embedded arrays (`attendance.records`, chat `messages`) into child rows.
5. Finance: create one `LedgerEntry` per invoice, payment, adjustment and refund; assert each student's balance equals v1's derived balance.
6. Validate: row counts, financial totals, orphan references, unique registration numbers.
7. Rehearse twice on staging; freeze v1 writes (read-only rules) for the final run; keep v1 online read-only for 30 days.

---

## 15. Quality, security, operations

- **Testing pyramid:** unit tests for services/policies → API tests for each endpoint → authorization matrix → a few Playwright journeys (login, enrol, attendance, record payment).
- **Security:** least privilege by default; rate limiting (`django-ratelimit`/DRF throttles); CORS allow-list; CSRF not needed for bearer-token API but keep secure cookies off; secure headers; dependency scanning (Dependabot); never log tokens or personal data.
- **Performance:** DB indexes for every foreign key and every filter field you expose; query-count tests on list endpoints; pagination everywhere.
- **Ops:** staging + production, migrations run on deploy, feature flags via settings, runbook for restore-from-backup and "database is waking up" incidents.

---

## 16. Decisions

**Made**
1. Roles: `SUPER_ADMIN, ADMIN, DIRECTOR, HOD, TEACHER, BURSAR, STUDENT` (BURSAR replaces `FINANCE`).
2. M-Pesa: first release after launch (v2.1). Launch uses manual M-Pesa code entry by the Bursar.
3. Files: real uploads are in v2.0.

**Still open (default if you don't decide)**
1. One campus or multi-campus from day one? *(Default: single campus; keep the optional `Campus` FK.)*
2. UI languages at launch? *(Default: English, with i18n scaffolding for Swahili.)*
3. Which API host? *(Default: decide at the end of Sprint 0 after testing cold-start behaviour.)*
4. GUARDIAN role in v2.0 or later? *(Default: later.)*

---

## Appendix A — Environment variables

**Backend**
```
DJANGO_SETTINGS_MODULE=config.settings.prod
SECRET_KEY=...
DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
FIREBASE_SERVICE_ACCOUNT_JSON={...}
ALLOWED_HOSTS=api.example.com
CORS_ALLOWED_ORIGINS=https://watantraininginstitute.ac.ke,https://www.watantraininginstitute.ac.ke,http://localhost:3000
SENTRY_DSN=...
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_BUCKET=watan-lms-files
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
```

**Frontend (public values only)**
```
VITE_FIREBASE_API_KEY=...  VITE_FIREBASE_AUTH_DOMAIN=...  VITE_FIREBASE_PROJECT_ID=...  VITE_FIREBASE_APP_ID=...
VITE_API_URL=https://api.example.com
VITE_TURNSTILE_SITE_KEY=...
```

## Appendix B — Go-live checklist

- [ ] Old Firebase service-account key revoked; new key only in host secrets.
- [ ] Authorization matrix covers every endpoint and passes.
- [ ] Every list endpoint is paginated and uses `for_user`.
- [ ] Ledger, grade revisions and audit log are append-only (app + DB trigger).
- [ ] Import rehearsal: zero mismatches; balances equal v1 for every student.
- [ ] Backups scheduled and a restore tested on staging.
- [ ] File uploads: bucket private, CORS locked, size/type checks verified at `complete`, orphan cleanup and quota alerts running.
- [ ] Cold-start (database/API waking) UX tested; retry logic verified.
- [ ] Data-protection review done; consent and retention settings configured.
- [ ] Rollback plan: v1 remains available read-only for 30 days.
