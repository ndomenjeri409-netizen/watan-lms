# Watan LMS v2: Master Guide (single source of truth)

**Status date:** 2026-11-13. Reconciled against the repository state through QR check-in roster authorization in Sprint 5.5 Step 4.
**Authority:** this file replaces the earlier planning documents (blueprint, multi-unit addendum, remaining-sprints, academic-flow, Section A, UI plans, Sprint 0). They are history in `docs/archive/` and must not be followed. If this guide and the code disagree, do **not** silently pick one: record the difference in `docs/DEVIATIONS.md` and ask the owner.
**Companions that stay separate:** `docs/PROGRESS.md` (living tracker), `docs/DEVIATIONS.md` (log), `docs/units.md`, `docs/department_unit_map.csv`, `docs/chart_of_accounts.csv` (+ `chart_of_accounts_notes.md`), `docs/UI_GUIDELINES.md`, `docs/RESOURCE_PAGE_RECIPE.md`, `.github/copilot-instructions.md`.

---

## 0. How Copilot must work (read every session)

### 0.1 Session start
1. Read `docs/PROGRESS.md` (what is done, what is next). Read the section of this guide for the current step. Read `docs/DEVIATIONS.md` if it exists.
2. If `PROGRESS.md` is empty, unreadable or contains NUL bytes, stop and tell the owner; do not invent history.

### 0.2 Step protocol (every step, no exceptions)
1. **Audit first** when a step says so: produce a table (item, done/partial/missing, evidence) and stop if the owner asked only for the audit.
2. Implement **one item at a time**. No extra features, apps, libraries or refactors.
3. Run the checks in section 11. Show results.
4. Update `docs/PROGRESS.md` (status, date, evidence, test counts). Never tick without evidence (test name, file path, query result).
5. **Stop** and report. Wait for the next instruction.

### 0.3 Anti-drift rules
| # | Rule |
|---|---|
| 1 | This guide wins over remembered conversation. Contradictions go to `docs/DEVIATIONS.md`, then ask. |
| 2 | No new dependency, app, service or provider without owner approval. |
| 3 | Every schema change ships with: migration, test, OpenAPI regeneration (`openapi.yaml` and `frontend/src/api/schema.d.ts`). |
| 4 | Every new model has a `unit` FK **or** an entry in the guard's exemption list with a reason (section 5.4). |
| 5 | Every new endpoint is unit-scoped (`ScopedViewSetMixin` or equivalent) and has role by unit tests. |
| 6 | Every audit record uses `record_audit(..., unit=...)` or `group_level=True`. System jobs use a named SYSTEM actor. |
| 7 | Money is `Decimal`; ledger, journal, payments, receipts, audit and grade revisions are append-only. Corrections are reversals with a reason. |
| 8 | **Never invent finance reference data** (accounts, thresholds, categories, payees, amounts, custodians, opening balances). Load only from approved files in `docs/`; if missing, stop and ask. |
| 9 | UI uses `AppShell`, `PageHeader` and `src/components/ui/*` only; colours come from tokens, never hex; no fake numbers; every data view has loading, empty and error states; errors show the server's message and field errors (never a bare "Request failed"). |
| 10 | User-facing text goes through `t()` (`src/lib/i18n.ts`). |
| 11 | Postgres-only tests use `@postgres_only`; CI must fail on any skipped test. |
| 12 | Never commit secrets or `.env` files. Never run destructive commands (drop, flush, reset, truncate, `docker compose down -v`) against the configured database without asking. |
| 13 | Docs must stay intact: `scripts/check_docs.py` (section 11.4) must pass; never leave a doc empty. |

### 0.4 Naming glossary (a past source of confusion)
| Term | Meaning | Where |
|---|---|---|
| **Business unit** | WTI, WTA, WDS, WCY, HQ (cost centres of one business) | `org.BusinessUnit`, field `unit` |
| **Curriculum unit** | A section inside a course module | `academics.Unit`, API `course-units`. In UI call it **Topic**. Never say "unit" for this in UI or docs |
| **Course** | The curriculum (what is taught) | `academics.Course` |
| **Class** | One delivery of a course for an intake | `scheduling.ClassGroup` |
| **Enrollment** | A student's place in a course (and class, once linked) | `enrollment.Enrollment` |
| **Cost centre** | The `unit` carried by every journal line | `finance.JournalLine.unit` |

### 0.5 Standing instruction: "run the system"
When the owner says run the system: use the real configuration in `backend/.env` and `frontend/.env.local` exactly as it is (database, storage, Firebase). Do not create mock backends or swap in SQLite. Run all needed migrations (`python manage.py migrate`) and seeds (`seed_units`), start backend (`runserver 8000`) and frontend (`npm run dev`), print the URLs. If a step fails, find the real cause and fix it. No lectures about secrets; the owner accepts they are replaced at official deployment. Still never commit secrets and never run destructive commands without asking.

---

## 1. Business context and decisions

### 1.1 The business
One business, four self-managed units that are **cost centres**, not separate legal entities, plus an `HQ` cost centre for shared items.

| Code | Unit | Offers | Notes |
|---|---|---|---|
| WTI | Watan Training Institute | Regular courses by department (ICT, Business & Finance Studies, Languages, Travel & Tourism) | Academic |
| WTA | Watan Travel Agency | GDS training (Amadeus, Travelport Level 1/2) | Department GDS maps here |
| WDS | Watan Driving School | NTSA driving courses and related services | Instructor/vehicle scheduling later |
| WCY | Watan Cyber | Cyber services | **Holds the institution's M-Pesa agent number** |
| HQ | Group/Shared | Shared costs | Not customer-facing |

- Students of WTI/WTA/WDS pay fees through the WCY-held M-Pesa agent number; teachers and workers are paid from it; some students pay cash. Unit managers hold **cash drawers** and pay petty expenses (tea, lunch, emergencies) from them. Units **reconcile cash flow at month end**; all revenue merges for consolidated audit.
- **Most students learn in physical classes (offline).** A login is **not** required for a student. Every student must still be registered for accounting and student management.
- Currency KES. Language English with i18n scaffolding for Swahili. Kenya Data Protection Act (2019) applies: collect only needed fields, restrict access to ID numbers and photos, define retention; get a qualified review.

### 1.2 Decisions log
| ID | Decision | Status |
|---|---|---|
| Roles | `SUPER_ADMIN, ADMIN, DIRECTOR, AUDITOR, UNIT_MANAGER, HOD, TEACHER, BURSAR, CASHIER, STUDENT` (STUDENT derived from the Student record) | Locked; built |
| M-Pesa | Automation is the first release after launch; v2.0 uses manual codes and statement import | Locked |
| Files | Real uploads in v2.0 | Locked |
| D1 | Registration number `UNIT/DEPT/YEAR/SEQ` (or `UNIT/YEAR/SEQ`); existing numbers never change | Done (A5) |
| D2 | Direct non-null `unit` on Department, Program, Course, Enrollment, TimetableSlot | Done (A4) |
| D3 | Audit entries from jobs use a named SYSTEM actor | Done (A3) |
| D4 | Both fixed terms and rolling intakes; assessments are course templates instantiated per class | Confirmed; AcademicPeriod and assessment template/instance split implemented |
| D5 | Teacher assignment at both class and course level | Confirmed; built (Step 1) |
| D6 | Student registration requires name, phone, unit, class; other fields optional | Confirmed; implemented in Step 5b |
| D7 | Duplicate warning on phone, or name plus date of birth, or national ID | Confirmed; implemented in Step 5b |
| D8 | Portal accounts only by staff-initiated invitation | Confirmed; implemented in Step 5a (2026-11-09) |
| D9 | Required `home_unit` stays the original registration identity unless an audited transfer changes it; registration numbers never change. Unit staff see students through home unit, enrollment, or invoice; teachers through taught classes; HODs through department enrollments; students see themselves; Directors/Auditors are group-wide read-only; Admin/Super Admin are global. Cross-unit duplicate checks reveal no details until one audited exact lookup by phone or registration number, which returns only name, home unit, and registration number; enrolling that student in a unit creates an enrollment. Restricted identity fields and guardian details are limited to Unit Managers, Bursars, Admin/Super Admin, and read-only Directors/Auditors. | **Confirmed 2026-11-13**; implemented in Step 5b |
| D10 | `Enrollment.class_group` FK (nullable until assigned, required when ACTIVE), with class.course = enrollment.course and same unit | **Confirmed 2026-11-09**; implemented (Step 4 D10) |
| D11 | Storage provider is Backblaze B2 (S3-compatible). Rename `R2_*` settings to `STORAGE_*` with backward-compatible aliases; verify region handling | **Confirmed 2026-11-08**; live smoke test remains |
| D12 | UI label for curriculum unit is "Topic"; code name unchanged | **Proposed** |
| D13 | Enrollment-keyed, append-only grade revisions; bounded attempts, enrollment-specific re-open grants, late cutoff, and staff-recorded grades | **Confirmed 2026-11-11**; implementation complete; migration and assessment tests passed on PostgreSQL 16.16 (isolated Neon branch, 2026-11-13); GitHub Actions run pending commit/push |

---

## 2. Architecture and conventions (as built)

```
React 19 + TS + Vite + Tailwind v4 + TanStack Query  ->  openapi-fetch typed client (generated from openapi.yaml)
Firebase Auth (login only)  ->  Bearer ID token  ->  Django 5 + DRF (verifies token, loads RoleAssignments)
Django services/transactions  ->  PostgreSQL (Neon)   |   files -> private S3-compatible bucket (signed URLs)
```
- **Backend:** Django + DRF, drf-spectacular, django-filter, firebase-admin, boto3, whitenoise, gunicorn; apps: `accounts, org, people, academics, enrollment, scheduling, attendance, assessment, finance, files, cms, audit` plus `common/`. Not yet present: `comms`, `assistant`, `reports` (only `GET /reports/overview` inside `accounts`).
- **Frontend:** pages `Login, Me, Users, Departments, CourseEditor, Courses (public), Apply (public), Students, Admissions, Scheduling, AttendanceCheckIn, Assessment, Finance`; shell with sidebar, top bar, unit switcher, theme toggle; UI primitives in `src/components/ui`; role by unit navigation in `src/app/navigation.ts`.
- **Contract pipeline:** `python manage.py spectacular --file openapi.yaml --validate` then `npm run api:types`. Never hand-edit generated files. API JSON is snake_case.
- **Pagination/filters:** DRF page number (default 25, max 100), django-filter, search, ordering; `?unit=<id>` validated against permitted units.
- **Errors:** `{code, message, fields}`; map to UI messages.
- **Database:** Neon Postgres via pooled URL; `DISABLE_SERVER_SIDE_CURSORS = True`; `.neon` and `neon.ts` hold Neon project config. Local: `docker compose up -d db` (Postgres 16, MinIO).
- **Storage:** private bucket, pre-signed PUT/GET, Django never proxies file bytes. D11 is owner-approved; settings use `STORAGE_*` with backward-compatible `B2_*` and `R2_*` aliases and derive Backblaze B2's signing region from the endpoint hostname. The live smoke test passed on 2026-11-08 (presigned PUT, HEAD, GET, DELETE, and browser PUT). The approved localhost CORS rule was added through the B2 Native API while preserving existing rules.
- **Free-tier realities:** verify current limits before relying on them (Neon scale-to-zero cold starts; storage caps; API host sleeping when idle). Keep API and DB in the same region. Weekly `pg_dump` backups via CI are required; do not rely on provider recovery for finance data.
- **Standing UI mechanics:** theme tokens live in `src/index.css` (see section 9); `scripts/check-colors.mjs` enforces the palette.

---

## 3. Repository map and environments

```
backend/  config/ (settings base/dev/prod, urls)  apps/<app>/{models,serializers,views,permissions,services,urls,migrations}
          common/ (scoping, audit, money, pagination, exceptions, health, permissions)  tests/  scripts/  requirements/
frontend/ src/{api,app,components/ui,features,lib,pages,test}  e2e/  scripts/check-colors.mjs
docs/     MASTER_GUIDE.md PROGRESS.md DEVIATIONS.md units.md department_unit_map.csv chart_of_accounts.csv ... archive/
.github/  workflows/ci.yml  copilot-instructions.md   (NOT present in the zip I reviewed: confirm they exist, otherwise recreate)
```
Env files: `backend/.env`, `frontend/.env.local` (git-ignored; `.env.example` committed). README is stale (still says Department.unit is nullable and "Sprint 1 starts here"): refresh it at R0.

---

## 4. As-built snapshot and gaps found in the code (Nov 2026)

Evidence base: models, urls, views, permissions, services and tests in the snapshot. Items marked **verify** were not proven by me.

### 4.1 What exists
- **Identity/roles:** `User` (firebase_uid, phone_number), `RoleAssignment` (unit-scoped), `RoleScope` (legacy department scope), Users page with assignment drawer, `report_pending_users` command.
- **Org:** BusinessUnit, Campus, Department(unit), Program(unit), AcademicPeriod (TERM/INTAKE, optional unit; legacy untyped periods are retained); `seed_units`.
- **People:** Student (user nullable, department, program, registration_number, phone, admission_year), StaffProfile, Guardian, per-unit `RegistrationSequence`; `report_registration_numbers`.
- **Academics:** Course (unit, version for optimistic locking, status, learning_outcomes, cover_image), CourseAssignment (can_edit_content), CourseModule, Unit (curriculum), Lesson (video_url, position, duration), Material (url or file).
- **Enrollment:** Application (public apply), Enrollment (unit, course, status), CourseAccess.
- **Scheduling/attendance:** Room, ClassGroup (course, legacy `teacher`, academic_period), ClassTeacher, TimetableSlot(unit); AttendanceSession (open/qr/close), QrToken, AttendanceRecord, CheckIn (client_checkin_id for offline sync).
- **Assessment:** Assessment (course and class_group), Submission, Grade (+GradeRevision, approval workflow), Gradebook, transcripts.
- **Finance:** Account, CashAccount, AccountingPeriod, FeeStructure (single amount, account mappings), Invoice, JournalEntry/JournalLine (unit, cash_account, student), Payment (normalized unique M-Pesa code), Receipt (generated file), Adjustment, Refund (maker-checker), journal guard triggers.
- **Other:** files (upload policies: material, cover_image, submission; cleanup command), cms (pages, FAQ, blog), audit (unit, scope, actor kind), `GET /reports/overview`.
- **Tests:** 125 backend test functions across 18 files (120 passed, 6 Postgres-only skipped on SQLite; CI run #11 passed 101 Postgres tests with no skips); 72 frontend tests; Playwright top-bar e2e.

### 4.2 Gaps and contradictions (ranked)

| # | Finding | Why it matters | Fix |
|---|---|---|---|
| G1 | **Authorization still has legacy single-role branches across the codebase.** The AC1 baseline found about 130 `user.role` uses and 45 `role_scopes` uses. AC3 has since fixed the people, enrollment, scheduling and attendance examples, including the missing UNIT_MANAGER attendance scope and multi-role scope union. Remaining apps and the generated authorization matrix are still pending. | Remaining branches can hide a secondary role's scope or capability; the matrix (A6) will expose gaps | Step AC (section 13): role-per-unit helpers, migrate each app, then matrix |
| G2 | **Student registration was coupled to Firebase account creation.** `approve_application` formerly created the Firebase user, `User`, and `Student` together | Prevented offline student registration and contradicted D8 | Resolved in Step 5a (2026-11-09) |
| G3 | **Teachers cannot mark attendance for a student.** Staff can only open/close sessions and show a QR; `check-in` is student-only. Records are read-only | Offline students can't be marked present | Step 4 |
| G4 | **Teachers cannot grade a student without a submission.** `Grade` is one-to-one with `Submission`, and only students create submissions | Offline students can't receive grades | Step 4 (Grade keyed by assessment plus enrollment; submission optional) |
| G5 | QR check-in still authorizes through CourseAccess rather than a class roster; class-specific attendance authorization remains absent | Attendance is not yet constrained to the enrolled class | Step 4 |
| G6 | Assessment carried both `course` and `class_group` | Ambiguous assessment ownership | Resolved in Step 4: course-owned templates and class-group instances |
| G7 | Student had no home unit, status lifecycle, date of birth or national ID; no duplicate warning; no CSV import; Student scoping ignored units | D6, D7, D9 | Resolved in Step 5b (2026-11-13); see people authorization/registration tests and end-to-end journey below |
| G8 | `Account` lacks `is_postable`; `seed_finance_accounts` reads a **JSON** file; no CSV loader; no CashAccount rows; `docs/chart_of_accounts.csv` was saved from Excel (TRUE/FALSE, CRLF) and its approval is unrecorded | B.1 blocked | R4 |
| G9 | FeeStructure has one `amount` (no instalments or due-date rules); Invoice is not linked to an enrollment; no statement PDF (verify) | B.5 | R4 |
| G10 | Receipts: stored on first download (verify generation at posting, per-unit numbering, VOID on reversal, content hash) | Audit integrity (B.4) | R4 |
| G11 | `docs/PROGRESS.md` is corrupted (14,150 NUL bytes) in both the zip and the upload; `.github/` absent from the zip | Lost status; CI unverifiable | R0 |
| G12 | README stale; storage settings named R2 with an R2 region; upload policies lack admissions documents, student photos and receipts | Confusion; later steps | R0, 6b |
| G13 | Curriculum `Unit` vs business `unit` naming collision | Copilot confusion | Glossary (0.4), D12 |

---

## 5. Authorization model

### 5.1 Roles
| Role | Scope | Can |
|---|---|---|
| SUPER_ADMIN | Group | Everything |
| ADMIN | Group | Operations across units; cannot grant SUPER_ADMIN or ADMIN |
| DIRECTOR | Group | Read-only dashboards and reports |
| AUDITOR | Group | Read-only finance, journal, audit log, exports; cannot change anything |
| UNIT_MANAGER | Unit(s) | Runs the unit: staff, courses, fees within policy, approves unit expenses; custodian of the unit's drawer; cannot see other units |
| HOD | Department in a unit | Approvals and reports for the department |
| TEACHER | Unit(s) | Own classes: attendance, grading; edits content only where `can_edit_content` |
| BURSAR | Unit(s) or group-wide | Payments, invoices, receipts, reconciliation; prepares refunds (approval required) |
| CASHIER | Unit | Records sales and payments; no refunds, no edits to posted entries (optional use) |
| STUDENT | Self | Own data; derived from the linked Student record |

Group roles carry no unit; UNIT_MANAGER, HOD, TEACHER, CASHIER require one; BURSAR either. Enforced by `RoleAssignment` constraints.

### 5.2 Three layers (all server-side)
1. **Role gate**: may this role use this endpoint at all.
2. **Row scope**: `Model.objects.for_user(user)`; `UnitScopedQuerySet` filters by `unit_field` (a path like `course__unit` is allowed for derived models); `?unit=` narrows to one permitted unit.
3. **Object/action rule**: may this user do this to this object (for example a teacher grades only their own class).
Global read is not global write: DIRECTOR and AUDITOR never write.

### 5.3 Target helper API (Step AC)
Replace `user.role` comparisons with explicit, unit-aware helpers in `apps/accounts` and `common/permissions.py`:
- `user.has_role_for_unit(role, unit_id)` and `user.unit_ids_for(*roles)` (units where the user holds any of those roles).
- `user.has_role_global(*roles)`; `can_write_unit(user, unit)` stays.
- Department-scoped HOD rights come from a HOD assignment plus `RoleScope`; define `user.department_ids_for_hod()` and use only that.
- `user.role` remains only for display ("primary role"); **it must not be used in permission code** after Step AC (add a lint test that fails on `user.role` in `permissions.py`, `views.py` and `models.py` querysets).

### 5.4 Guards that must always pass
- Every concrete `ModelViewSet` inherits `ScopedViewSetMixin`; every non-model view is on the guard's allow-list with a reason.
- Every model in unit-owned apps has a `unit` field or an exemption with a reason. Current derived-unit models (via path): CourseModule, curriculum Unit, Lesson, Material, Application, CourseAccess, ClassGroup, AttendanceSession/Record/QrToken/CheckIn, Assessment, Submission, Grade, GradeRevision, Payment, Receipt, Adjustment, Refund; group-level: Campus, AcademicPeriod, Account, AccountingPeriod, JournalEntry (lines carry unit); explicit custody unit: CashAccount; person records: Student, StaffProfile, Guardian, StoredFile.
- A6 (generated matrix): see section 13.

### 5.5 Authentication flow
Firebase ID token in `Authorization: Bearer`; `FirebaseAuthentication` verifies, gets or creates `User` (no role = awaiting approval, only `/me`). Role changes only via the assignments API (ADMIN cannot escalate; last SUPER_ADMIN protected; audited with unit). Invites/provisioning are server-side (Admin SDK) and **staff-initiated** (D8).

---

## 6. Academic flow and students

### 6.1 Model: curriculum versus delivery
```
BusinessUnit > Department > Program > Course (curriculum) > CourseModule > Topic (academics.Unit) > Lesson > Material
Course + AcademicPeriod + cohort  >  Class (ClassGroup)  >  ClassTeacher, TimetableSlot > AttendanceSession > AttendanceRecord
                                      Enrollment (student in the class) > Invoice(s), Grades, Attendance
Assessment template (on Course)  >  Assessment instance (per Class, with dates)  >  Submission (optional)  >  Grade (per enrollment)
```
Why: the same course runs in many intakes; teachers, rooms, dates, attendance, grades and fees differ per intake; editing curriculum must not rewrite history.

### 6.2 Rules
- **Teacher assignment:** `ClassTeacher` (teaches a class: roster, attendance, grades for that class) and `CourseAssignment` (`can_edit_content` for curriculum). `ClassTeacher.Role.LEAD` is the canonical class lead; HOD and UNIT_MANAGER manage assignments within their department/unit. `ClassGroup.teacher` has been backfilled to active LEAD assignments by `scheduling.0005` and dropped. Class creation requires `lead_teacher`; responses expose read-only `lead_teacher_id` and `lead_teacher_name`. Reassigning the lead through the class-teacher API promotes the new LEAD and demotes the prior lead to ASSISTANT, retaining both active assignment records and auditing the change.
- **Course lifecycle:** `DRAFT > PUBLISHED > ARCHIVED`; editable any time with audit and the `version` optimistic lock. A course's unit is immutable. Its department may change only within the same unit, and only while it has no classes, enrollments, course access or graded assessments. Once classes or enrollments exist you cannot delete modules, topics, lessons or assessments that have grades or attendance (archive them). Actions: publish, unpublish, duplicate (to a new draft), archive/unarchive; reorder modules, topics and lessons with stored `position`.
- **Class lifecycle:** `PLANNED > OPEN > RUNNING > COMPLETED`, with cancellation allowed before completion. New classes require a PUBLISHED course, an academic period, cohort name and positive capacity; at least one active teacher assignment is required before RUNNING. Capacity is enforced at enrollment, and timetable clashes (teacher, room, class) are rejected. Cancellation or archive is blocked while ACTIVE enrollments remain; cancellation closes open attendance sessions and deactivates timetable slots. HOD approval of final grades must lock the class; integrate that lock with the assessment/grade work below.
- **Enrollment (D10):** `Enrollment.class_group` is nullable until assigned and **required when ACTIVE**; activation validates matching course and unit, active class status, and capacity. The database also requires a class for ACTIVE enrollments. The attendance roster is the class's ACTIVE enrollments; QR check-in must authorize through that roster, not only course access. Production had zero students at the last promotion, so changing this now is cheap.
- **Academic periods (D4):** `kind` (TERM or INTAKE) and optional `unit` are implemented. Legacy periods keep a nullable kind rather than being guessed from their names; new periods require a kind, and new classes require an active typed period compatible with the course unit. HODs and unit managers see group-wide and assigned-unit periods.
- **Assessment (D4, D13):** course template; class instance with `max_attempts` (default 1, minimum 1), `due_at`, optional `late_until` (strictly after `due_at`), weight, and status. A submission after `due_at` and through `late_until` is flagged late without an automatic mark penalty. When `late_until` is null, `due_at` is the strict cutoff; an enrollment-specific re-open grant is the only exception.
- **Grades and attempts (D13):** one `Grade` per (assessment instance, enrollment), with append-only revisions; each submission attempt creates a DRAFT revision linked to that submission. Earlier SUBMITTED, APPROVED, or PUBLISHED revisions are never changed or deleted. Approval and publication are distinct, audited actions; APPROVED-but-unpublished revisions are not official. The latest PUBLISHED revision is official; a newer DRAFT, SUBMITTED, or APPROVED revision is shown as "Regrade pending." "Approve and publish" runs both steps atomically. Approvers and publishers are scoped HOD/UNIT_MANAGER, ADMIN, or SUPER_ADMIN; each must differ from the grader and, for granted re-sits, the grantor. Staff-recorded marks for learners without portal accounts use source `STAFF_RECORDED`, have no submission, and do not increment the submission attempt number. Before class lock, a teacher may record a mark revision without a grant while the enrollment remains within the attempt limit; each revision has a note and approval workflow. After lock, a grant is required and consumed when the revision is recorded.
- **Attempt limit, late cutoff, and re-open grants (D13):** students may submit up to `max_attempts`. Submissions through optional `late_until` are flagged late without an automatic penalty; null `late_until` makes `due_at` the strict cutoff. A grant is scoped to one assessment and enrollment, adds exactly one submission attempt, requires a reason and `valid_until` (default seven days; maximum 30 days), and expires unused. It can override CLOSED state and due/late cutoff only for that enrollment; the assessment must be PUBLISHED or CLOSED, and the enrollment ACTIVE or COMPLETED. Every grant and use is unit-audited. When a class is completed or final grades are locked, only HOD, UNIT_MANAGER, ADMIN, or SUPER_ADMIN may grant; otherwise the assigned class teacher, scoped HOD/UNIT_MANAGER, or ADMIN/SUPER_ADMIN may grant.
- **Re-sits after class lock (D13):** the assigned ClassTeacher may grade only the granted enrollment's new revision; if no assigned teacher is active, HOD, UNIT_MANAGER, ADMIN, or SUPER_ADMIN may grade it. Approval and publication each require a different person from both grader and grantor: scoped HOD, UNIT_MANAGER, ADMIN, or SUPER_ADMIN; escalate to ADMIN/SUPER_ADMIN if no eligible person remains. The class and all other enrollments/grades stay locked. The previous official revision remains official until the new revision is published; record its supersession without changing or deleting it. Each publication creates a dated revised transcript/report-card version and retains prior versions. Offline re-sits use a staff-recorded revision with no submission and the same grant/approval rules after lock. Optional scanned-script evidence may use the submission file purpose; it is not required.
- **Attendance:** teacher/HOD bulk marking (present, absent, late, excused) is restricted to ACTIVE enrollments in the class roster, one record per student per session, idempotent, and offline-friendly. QR self check-in requires an ACTIVE enrollment in the scanned session's class, not merely course access; it stays available to students with accounts (and later printed cards scanned by the teacher).

### 6.3 Students without accounts (offline learners)
A student is a **record**; a login is optional.
- **Fields:** full name; registration number (per unit); phone (**required**, primary contact); email optional; guardian/sponsor optional (recommended for minors); date of birth optional; national ID or birth certificate optional and restricted; photo optional (files app); county/area; status `APPLICANT > ACTIVE > COMPLETED, WITHDRAWN, SUSPENDED, DEFERRED`; `home_unit` (D9); `user` nullable with `account_status` `NONE, INVITED, ACTIVE`.
- **Visibility (D9):** Unit Managers, Bursars, and Cashiers see students through their assigned unit's `home_unit`, enrollments, or invoices; teachers see students in classes they teach; HODs see students with enrollments in their assigned departments. Students see themselves. Directors and Auditors have group-wide read-only visibility; Admin and Super Admin have global access. Unit Managers may manage records only within their assigned units, even when a separate teacher assignment gives them additional read visibility.
- **Privacy (D9):** date of birth, national ID/birth-certificate details, photo, and guardian details are available only to Unit Managers and Bursars in scope, Admin/Super Admin, and group-wide read-only Directors/Auditors. Teachers and Cashiers receive only basic name, registration, phone, and class information.
- **Duplicate handling (D9):** duplicate checks use phone, national ID, or name plus date of birth. A hidden cross-unit candidate is not disclosed; the registering staff member may perform one audited exact lookup by phone or registration number. A match returns only name, home unit code, and registration number with a short-lived enrollment action; “Enroll in my unit” creates a normal enrollment without changing the original registration number.
- **Transfers (D9):** changing `home_unit` is an explicit audited transfer; it never reallocates or changes the registration number.
- **Migration (D9):** backfill `home_unit` from a recognized unit prefix, otherwise from the department's unit. Print aggregate prefix/fallback/unmappable counts before writes, and fail with student identifiers and registration numbers if any row cannot be mapped. Do not silently guess.
- **Flows with no login:** front-desk registration in under a minute (name, phone, unit, class); CSV import with a validation report; duplicate warning (D7, staff confirms); staff enrol, invoice, record payments, print receipts and statements; teachers mark attendance and enter grades; staff print report cards and certificates; optional "Invite to portal" when an email exists.
- **Application approval must not force an account (D8):** approval creates the Student (with registration number) and optionally enrolls; the Firebase user is created only by the explicit invite action. Public `/apply` must not require an email.

---

## 7. Finance

### 7.1 Principles
One shared chart of accounts for the whole business. Every journal line carries a `unit` (cost centre). Where money physically sits is a **cash account** (unit drawers, the WCY-held M-Pesa agent float, bank). Append-only journal with reversals, balanced entries, closed periods reject postings.

### 7.2 As built (keep)
Journal engine posts balanced entries for invoice, payment, refund, adjustment and reversal with unit on every line and cash_account on cash lines; idempotency keys; M-Pesa code normalized and unique across the business (partial unique + check); maker-checker on refunds, waivers and voids with mandatory reasons; student balance computed from journal lines (test proves equality with invoices); Postgres guard triggers proven in CI.

### 7.3 Chart of accounts (R4 first task)
- `docs/chart_of_accounts.csv` columns: `code, name, type, parent, is_cash, is_postable` (92 rows: 71 postable, 21 headers; drafted for your accountant; **record who approved it and when in PROGRESS before loading to production**).
- Build `seed_chart` (idempotent, upsert by code, parents by code, **case-insensitive TRUE/FALSE, tolerate CRLF and BOM**, never delete accounts with postings) and add `Account.is_postable` (posting to a header is rejected). Replace or extend `seed_finance_accounts` (currently JSON).
- Create `CashAccount` rows for 1110 to 1113 (drawers), 1120 (M-Pesa agent float, `custody_unit` WCY) and 1130 (bank, delete if none) **only from an approved custodian list**; never invent custodians or opening balances.
- Maps load from `docs/` config, not code constants: petty-cash categories (TEA_LUNCH to 6130, EMERGENCY to 6390, TRANSPORT to 6340, SUPPLIES to 6330, OTHER to 6390) and statement classes (STUDENT_FEE, STAFF_DISBURSEMENT, CYBER_SERVICE_SALE, PUBLIC_AGENT_TXN, FLOAT_TOPUP_OR_TRANSFER, COMMISSION, CHARGES, UNKNOWN to suspense 2250).
- Posting recipes (see `chart_of_accounts_notes.md`): invoice Dr 1210 Cr 4110 (or 4120 to 4160); fee by M-Pesa Dr 1120 Cr 1210 (or 2250 if unidentified); cash fee Dr unit drawer Cr 1210; waiver Dr 4910 Cr 1210; refund Dr 4920 (or 2210) Cr cash; teacher paid from float Dr 5110 Cr 1120; petty voucher Dr expense Cr drawer; drawer variance 6920; commission Cr 4310; charges Dr 6380.

### 7.4 Cash custody and M-Pesa agent (Sprint 6b)
- **Cash accounts:** agent float (custodian WCY), drawer per unit (custodian unit manager), bank. Transfers between them need sender and receiver signatures.
- **Fee through the agent number:** staff record student, invoice, amount, channel, **code (required, unique)**, payer phone; receipt shows the unit. Unmatched statement lines go to an "unidentified deposits" worklist.
- **Disbursements (teachers, workers):** states `REQUESTED > APPROVED > EXECUTED > RECONCILED` (or `REJECTED`); requester = manager of the cost-centre unit; approver = ADMIN/SUPER_ADMIN, never requester or executor; executor = agent-number operator records the code; payee register with verified phones (changes need approval); per-payee and daily limits; daily float report.
- **Petty cash (imprest):** per-drawer float; voucher categories TEA_LUNCH, EMERGENCY, TRANSPORT, SUPPLIES, OTHER; receipt required above a threshold; countersign above a limit; overdraft blocked; emergencies flagged next day; daily drawer count with variance explanation.
- **Public agent traffic** (if the number serves the public) is pass-through, not income; every statement line is classified; UNKNOWN blocks month-end close.

### 7.5 Month-end close (Sprint 6c)
Drawer counts signed > statement imported > auto-match by code, amount, time, phone > classify and resolve > unit month summaries > unit sign-offs (`UnitPeriodSignoff`) > ADMIN approval and period lock > auditor review. Reports: unit month summary, consolidated by unit, custody report, settlement position by unit (informational), receivables ageing, collections by day and channel; auditor workspace with drill-down from report line to entry to source document to receipt; exports logged.

### 7.6 Controls and segregation of duties
| Step | Who | Must not be |
|---|---|---|
| Record fee payment | Bursar or clerk | Refund approver |
| Reverse, refund, waive | Prepared by bursar | Approved by the same person |
| Request disbursement | Manager of the cost-centre unit | Approver or executor |
| Approve disbursement | ADMIN or SUPER_ADMIN | Requester or executor |
| Execute (send M-Pesa) | Agent-number operator | Approver |
| Reconcile statement | Bursar or group accountant | Executor of the same payments |
| Close period | ADMIN or SUPER_ADMIN | Before all unit sign-offs |
| Review | AUDITOR (read-only) | Anyone who posts |

### 7.7 Receipts (B.4)
Generate the PDF **when the payment posts** (background job), not on first download; sequential number per unit (counter row with lock); shows unit, student, invoice, amount, channel, code, issuer; reversal re-stores a VOID-marked version; store a content hash.

### 7.8 Fee structures and invoicing (B.5)
Per unit and course/program; instalment plans and due dates; invoice linked to the enrollment; invoices generated from enrollment plus fee structure; student statement PDF. M-Pesa Daraja callbacks generally need a Paybill or Till, not necessarily an agent number: confirm with Safaricom; until then statement import is the plan.

### 7.9 Open finance inputs
Approved chart; custodians and opening balances; imprest amounts; petty-cash thresholds and categories; approval thresholds and daily limits; payee list; redacted M-Pesa agent statement; answers on public use of the agent number, commission treatment (WCY or HQ) and cash-back mechanics; shared-cost treatment (HQ or split); financial year and sign-off deadline; VAT or e-invoicing applicability; payroll scope (recommended no for v2.0).

---

## 8. Files

- Private bucket; upload flow: `POST files/uploads` (policy check, creates PENDING) > browser PUT to bucket > `POST files/{id}/complete` (HEAD verifies size and type, sniff content) > READY; download via short-lived signed GET authorized by the **owning object's** policy.
- Policies today: `material` (25 MB), `cover_image` (3 MB), `submission` (20 MB). To add: `student_photo` (3 MB), `admission_document` (5 MB), `receipt` (petty cash, 5 MB), `generated` (system PDFs).
- Random object keys, never user filenames; `Content-Disposition: attachment` for non-images; orphan cleanup (`cleanup_pending_uploads`); quota guard (`FILE_STORAGE_QUOTA_BYTES`, alert at 70%, block at 95%); videos stay external links.
- Storage interface stays provider-agnostic (D11).

---

## 9. UI and UX system

### 9.1 Palette (exactly six brand colours; everything else derived by opacity or `color-mix`)
`ink #0D0E12` (app background, sidebar, text on light and on amber) · `panel #181A22` (cards, drawers, active nav) · `amber #FFAE1B` (primary actions, active indicator, focus on dark, progress) · `violet #8F41FF` (secondary accent, selected, info) · `white #FFFFFF` · `mist #A0A5B5` (muted text on dark). Two functional status colours (success green, danger red) are the only extras. Hex values exist **only** in the `@theme` block of `src/index.css`.
Contrast rules: text on amber is always ink; never white on amber; violet is never small text on dark (fills, badges with white text, icons, chart series); mist is never text in the light theme; amber is never text or thin lines on white; light-theme focus ring is ink. Default theme is dark.

### 9.2 Shell and patterns (built; keep)
Sidebar (ink, grouped by role, active item panel plus 3 px amber bar), top bar (menu, unit switcher native select/chip, search stub with platform-aware shortcut hint, theme toggle, avatar menu), responsive: phones show icon search overlay and unit code chip, no shortcut hint, 44 px targets, no horizontal scroll (Playwright test covers 320 to 1280 px). Pages follow `docs/RESOURCE_PAGE_RECIPE.md`: `PageHeader` + toolbar + `DataTable` (server pagination) + `Drawer` forms + confirm `Dialog` + toasts; archive, never delete, where history exists. `Departments.tsx` is the reference page.

### 9.3 Dashboards
Role-aware, real data only from `GET /reports/overview` keys (a card without data is hidden); admin gets a "Getting started" checklist; teacher gets action lists (today's schedule, needs grading); student gets next class, deadline, fee balance, announcements; HOD approval queues; bursar collections and reconciliation items; director and auditor consolidated KPIs.

### 9.4 UX backlog to verify (from the polish plan)
Complete-profile banner (names still show the email prefix when `display_name` is empty); `Ctrl K` command palette; `roleLabel()` sentence case; scrollbars dark in the sidebar; breadcrumbs from navigation config; WCAG AA contrast test; i18n through `t()`. Mark each done only with evidence.

---

## 10. Data pipeline and operations

- **Request path:** React > typed client > Django (authenticate > role gate > scoped queryset > service layer in `transaction.atomic` with `select_for_update` where races matter > serializer). Multi-step business operations live in `services.py`, views stay thin.
- **Background work (to build):** a Postgres-backed queue (for example procrastinate or django-q2) for PDFs, emails/SMS, exports, reminders, retention; on hosts without a second process, run as scheduled jobs.
- **Domain events:** explicit `publish("event", payload)` helper rather than hidden signals (enrollment approved creates course access, audit, notification).
- **Real time:** TanStack Query refetch and short intervals; SSE later only if needed.
- **Backups and CI:** weekly `pg_dump` artifact via GitHub Actions; CI runs ruff, `makemigrations --check`, pytest on Postgres 16 with `REQUIRE_POSTGRES_TESTS=1` and skip-fails, OpenAPI drift check, frontend lint, typecheck, tests, build, colour check, docs integrity check.
- **Data protection:** consent, retention, restricted fields, audit of exports.

---

## 11. Quality gates

### 11.1 Commands
Backend (in `backend/`): `pytest`, `ruff check .`, `ruff format --check .`, `python manage.py makemigrations --check --dry-run`, `python manage.py spectacular --file openapi.yaml --validate`.
Frontend (in `frontend/`): `npm run api:types`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`; e2e: Playwright topbar spec.

### 11.2 Definition of done (every step)
- [ ] Tests: unit tests, **role by unit** tests for every new endpoint, constraint tests; Postgres-only tests marked `@postgres_only`.
- [ ] Guards pass (viewset scoping, unit-or-exempt, no `user.role` in permission code after Step AC).
- [ ] Migrations apply on Postgres (CI) and are safe on existing data; data migrations fail loudly on unmapped data, never guess a unit.
- [ ] OpenAPI and TS types regenerated; CI drift check green.
- [ ] Audit records written with unit or group_level; money and ledger append-only.
- [ ] UI: shell, tokens, three data states, server error messages, mobile check at 390 px, `t()` strings.
- [ ] `docs/PROGRESS.md` updated with evidence; `docs/DEVIATIONS.md` updated if the guide and code differ.
- [ ] No secrets committed; app starts with the standing run instruction.

### 11.3 Test conventions
Fixtures create units A and B and one user per role profile (anonymous, awaiting approval, SUPER_ADMIN, ADMIN, DIRECTOR, AUDITOR, UNIT_MANAGER own/other unit, HOD, TEACHER, BURSAR unit/group, CASHIER, STUDENT self/other, multi-role user). Never run tests against the configured production database; CI uses its own Postgres service.

### 11.4 Docs integrity check (prevents a repeat of the corrupted PROGRESS.md)
`scripts/check_docs.py` (run in pre-commit and CI): for every `docs/*.md` and `docs/*.csv`, fail if the file is empty or contains a NUL byte (`b"\x00"`), and fail if `docs/PROGRESS.md` lacks the headings "Sprints" and "Section A". Commit docs after every step.

---

## 12. Loophole register (problem we hit, rule, enforcement)

| Problem found | Rule | Enforced by |
|---|---|---|
| Postgres-only tests silently skipped | `@postgres_only`; CI fails on skip | CI env `REQUIRE_POSTGRES_TESTS=1` + skip check |
| Unscoped viewset could leak across units | Every ModelViewSet scoped | `test_guards.py` |
| Model added without a unit | Unit FK or exemption with reason | `test_guards.py` |
| Audit rows without unit or actor | `record_audit` requires unit or group_level, actor or SYSTEM label | `test_audit.py`, constraints |
| Department without unit | Non-null unit; mapping file; fail on unmapped | Migration A4, `department_unit_map.csv` |
| Registration number collisions or renumbering | Atomic per-unit sequence; immutable numbers | A5 tests |
| Duplicate M-Pesa code reuse | Normalized, unique across business | Partial unique + check constraint test |
| Legacy single-role authorization | Role-per-unit helpers; ban `user.role` in permission code | Step AC lint test |
| Student only creatable with a Firebase account | Student record independent of account | Step 5a test |
| Staff cannot mark attendance or grade for offline students | Bulk mark and mark entry endpoints | Step 4 tests |
| Enrollment not tied to a class | `Enrollment.class_group` rules | Step 4 constraint tests |
| Bare "Request failed" errors | Show server message and field errors | UI test per drawer form |
| Wall of "Available soon" dashboard cards | Hide cards without data; real counts only | `dashboard.test.tsx` |
| Stray hex colours or default Tailwind palette | Tokens only | `check-colors.mjs` |
| Top bar overlap on phones | 44 px targets, no overflow at 320 to 1280 px | Playwright topbar e2e |
| Finance reference data invented by the assistant | Only approved files in `docs/` | Rule 8; review |
| Receipt integrity (generated late, no VOID) | Generate at posting; VOID on reversal; hash | B.4 tests |
| Docs lost or corrupted | Non-empty, no NUL; commit often | `check_docs.py` |
| Guide versus code drift | Log in DEVIATIONS.md; ask | Session protocol |
| Storage provider mismatch (R2 names, region) | Provider-agnostic `STORAGE_*`; smoke test | Step R0.2 |

---

## 13. Roadmap (status and next steps in order)

### 13.1 Status board
| Item | Status |
|---|---|
| Sprints 0, 0.75, 1 to 5 | DONE (gaps G1 to G7 found; addressed below) |
| Section A (A1 to A5) | DONE; **A6 matrix IN PROGRESS** |
| Sprint 5.5 Step 1 teacher assignment | DONE (2026-11-07) |
| Sprint 5.5 Step 5a student accounts | DONE (2026-11-09) |
| Sprint 5.5 Step 2 course lifecycle and editor | DONE (2026-11-09) |
| Sprint 5.5 Step 4 D10 enrollment-to-class link | DONE (2026-11-09); remaining Step 4 work is in progress |
| Sprint 5.5 Step 4 ClassTeacher lead canonicalization | DONE (2026-11-10); class-roster attendance and QR authorization are done; end-to-end journey passed (2026-11-13) |
| Sprint 6a | B.2 DONE; B.1, B.3 to B.6 PENDING or PARTIAL |
| Sprints 6b, 6c, 7, 8, 9 | PENDING |

### 13.2 Order of work
`R0 > AC > 5a > Step 2 > Step 3 > Step 4 > Step 5b > Step 6 > A6 > R4 (6a closure) > 6b > 6c > 7 > 8 > 9 > post-launch`

**R0: housekeeping (about half a day)**
- [ ] Rebuild `docs/PROGRESS.md` (use the provided file); add `scripts/check_docs.py` to pre-commit and CI; commit docs.
- [ ] Move superseded docs to `docs/archive/` with a banner "SUPERSEDED by MASTER_GUIDE.md; do not follow".
- [ ] Confirm `.github/workflows/ci.yml` and `.github/copilot-instructions.md` exist (replace the latter with the provided file); refresh README.
- [x] R0.2 storage: D11 confirmed; `STORAGE_*` settings with `B2_*`/`R2_*` aliases and endpoint-region handling implemented. Real-bucket presigned PUT, HEAD, GET, DELETE, and browser CORS PUT passed on 2026-11-08.
- [x] Create `docs/DEVIATIONS.md` (empty log with a header).

**AC: authorization consolidation (P0; fixes G1)**
- [x] AC1 Audit: table of every permission class, queryset `for_user` and view using `user.role` or `role_scopes`, with the roles they omit (UNIT_MANAGER, AUDITOR, BURSAR, CASHIER, multi-role cases); see `docs/AUTHORIZATION_AUDIT.md`.
- [x] AC2 Add `has_role_for_unit`, `unit_ids_for`, `has_role_global`, and `department_ids_for_hod` with role-assignment tests; `can_write_unit` remains in place.
- [x] AC3 Migrate app by app in this order: people (Student, Guardian, StaffProfile), enrollment, scheduling, attendance, academics, assessment, files, cms, org, accounts. Each app: replace `user.role` with helpers, include UNIT_MANAGER where it manages the unit, define AUDITOR/DIRECTOR as read-only, fix HOD scope, add role by unit tests (including a TEACHER in WTI and UNIT_MANAGER in WTA). **People, enrollment, scheduling, attendance, academics, assessment, files, CMS, org, and accounts apps complete. Remaining authorization matrix work is tracked in Section A6.**
- [x] AC4 Add the lint test banning `user.role` access in permission, view, and queryset code, with only the display-only response field allowlisted.
- **Done when:** a unit manager, bursar, auditor and teacher each see exactly the students and records their assignments allow, in API and UI.

**Sprint 5.5 (remaining)**
- **5a Decouple accounts (G2, D8):** `approve_application` creates the Student (registration number, `user` null) and does not touch Firebase; public apply does not require email; new action `POST students/{id}/invite` creates the Firebase user, `User` and links it (staff-initiated, audited); `account_status` field; tests including the no-email path and a failed invite that leaves the Student intact.
- [x] **5a complete (2026-11-09):** approvals create unlinked students without Firebase; public applications accept no email; in-scope staff can invite and audit; account status transitions NONE -> INVITED -> ACTIVE. Regression tests cover the no-email and failed-invite rollback paths.
- [x] **Step 2 Course lifecycle and editor (2026-11-09):** course details can be edited after creation; publish, unpublish, duplicate, and archive are versioned and unit-audited. The unit is immutable; only administrators and the course's unit manager can move a department, and only within the same unit while there are no classes, enrollments, course access rows, or assessments with submissions/grades. Program consistency is validated and moves are audited. Course deletion is disabled; the explicit archive action is soft. Stale or missing versions are rejected with a refresh message.
- [x] **Step 3 Curriculum tree (2026-11-09):** modules, topics, lessons, and materials can be edited, archived, reordered where applicable, and independently shown/hidden. Reordering persists atomically with audit records; file materials use the files app upload flow; the editor has a student-view preview. Video links require HTTPS and are restricted to `youtube.com`, `youtu.be`, `vimeo.com`, and their subdomains.
- **Step 4 Class link and offline operations (G3 to G5) — IN PROGRESS:** D10 enrollment-to-class link, base class creation/status rules, AcademicPeriod `kind`/`unit`, ClassTeacher LEAD canonicalization, HOD final-grade locking, Assessment template/instance split, D13 enrollment-keyed grade revisions/attempt grants/offline marks, roster attendance marking, and QR check-in authorization through the active class roster are implemented. The end-to-end course-to-grade journey passed on 2026-11-13. D13 migration tests (2) and the full assessment test module (13) passed on isolated PostgreSQL 16.16; an actual GitHub Actions run still requires commit/push. Timetable teacher/room/class clash checks already exist and are covered. End-to-end test: create course > publish > class > lead teacher > timetable > enrol > mark > grade > approve.
- [x] **HOD final-grade locking (2026-11-11):** A running class completes only after all active enrollments have a published grade for every class EXAM assessment; premature completion and post-completion submissions are rejected.
- [x] **Assessment template/instance split (2026-11-11):** Course-owned templates hold title, instructions, kind, and maximum score; class-group assessment instances hold due date, weight, and status. Existing assessments are migrated to templates; the workspace can reuse a template or create one with an instance. SQLite regression suite, migration drift, Ruff, OpenAPI/type generation, frontend typecheck/lint/tests passed. The migration has not been applied to a live database.
- [x] **D10 enrollment-to-class link (2026-11-09):** `Enrollment.class_group` is nullable until assigned and required for ACTIVE; activation validates course/unit, class activity, and capacity. Approval leaves enrollment APPROVED until it is assigned and activated. Database constraint and focused tests added.
- [x] **Base class creation and lifecycle (2026-11-09):** `ClassGroup.status` follows PLANNED > OPEN > RUNNING > COMPLETED, with cancellation before completion. Creation requires a published course, active typed period compatible with the course unit, cohort name, and positive capacity; RUNNING requires an active teacher. Cancellation closes sessions and deactivates timetable slots, and is blocked while ACTIVE enrollments remain. Existing rows default to PLANNED; the migration has not been applied to a live database. HOD grade-approval locking remains with assessment work.
- [x] **AcademicPeriod D4 fields and scope (2026-11-09):** Added TERM/INTAKE kind and optional unit. Existing periods remain untyped rather than being inferred; new periods require a kind. Period reads are scoped to group-wide and assigned-unit records, and class creation filters to active, typed, unit-compatible periods. The admin Scheduling drawer creates typed periods. Migration `org.0008` is generated but has not been applied to a live database.
- [x] **ClassTeacher lead canonicalization (2026-11-10):** Inspected `scheduling.0003` legacy lead backfill, added an idempotent reconciliation before `scheduling.0005` drops `ClassGroup.teacher`, and preserved any conflicting assignment by demoting the former LEAD to ASSISTANT. Class creation requires an active in-unit `lead_teacher`; output contains the current lead id/name, and authorized managers can replace a lead through a LEAD assignment action with audit records. Teacher access now follows active ClassTeacher assignments in class, attendance, assessment, people, and report querysets. Regression evidence: migration idempotency test and lead replacement test in `backend/tests/test_scheduling_migrations.py` and `backend/tests/test_scheduling_attendance.py`. The migration has not been applied to a live database.
- [x] **Roster attendance marking (2026-11-12):** Teacher/HOD bulk marking accepts only students with ACTIVE enrollments in the session's class, updates one record per student/session idempotently, and audits changes. The roster and mark endpoints are covered by `test_staff_bulk_marks_only_active_class_roster_and_is_idempotent` and `test_scoped_hod_can_bulk_mark_attendance_in_their_department` in `backend/tests/test_scheduling_attendance.py`.
- [x] **QR check-in roster authorization (2026-11-13):** A valid QR token permits check-in only for an ACTIVE enrollment in that token's session class; course access alone does not grant attendance. Focused check-in and roster tests passed on isolated in-memory SQLite (7 tests), including inactive enrollment, cross-class rejection, and check-in without CourseAccess.
- [x] **End-to-end class journey (2026-11-13):** `tests.test_academic_journey.AcademicJourneyTests.test_course_to_attendance_to_published_grade_journey` passed on isolated in-memory SQLite, covering course creation/publication, class/lead and timetable creation, front-desk registration without a portal account, invoicing/payment/receipt, roster attendance, offline grade approval/publication, student statement data, and the printable transcript.
- [x] **Step 5b Student registration (D6, D7, D9, G7) complete (2026-11-13):** front-desk registration, home-unit migration, scoped visibility/privacy, exact duplicate lookup/enrollment, and CSV import are implemented. Ten people authorization/registration/import tests and two migration backfill success/failure tests passed on isolated SQLite; the end-to-end no-account finance/attendance/grade/statement/transcript journey passed in `backend/tests/test_academic_journey.py`. No live migration was run. Student statement PDF remains in finance B.5.
- **Step 6 Tests and docs — IN PROGRESS:** Added endpoint role-matrix coverage for the Step 5b student write routes and profile-photo uploads; added API coverage for unit-scoped registration/import/enrollment/transfer/status; fixed restricted student-field and profile-photo access to honor the student's unit scope for multi-role users. Added `CourseEditConcurrencyTests.test_only_one_concurrent_update_with_the_same_version_succeeds` as a PostgreSQL-only concurrency test. The stale Grade fixture in `test_graded_assessment_blocks_course_department_move` now includes its required assessment, enrollment, and source. All 47 focused people/file/academics tests passed on SQLite except the expected PostgreSQL-only skip (46 passed, 1 skipped); verify the concurrent-edit test in PostgreSQL CI. README and PROGRESS updated; no live migration was run.

**A6: authorization matrix (generated, not hand-written)**
- [x] Generated a URLConf/router inventory in `backend/tests/authz_matrix.yaml`; the coverage test currently matches all 220 API method/path operations.
- [x] Added a parametrized 403 invariant for DIRECTOR and AUDITOR writes across the inventory; it exposed and fixed write access through profile PATCH, public application submission by authenticated read-only roles, file uploads, and user-assignment actions.
- [x] Added expected status and scoped-row assertions for 16 actor profiles on units, departments, courses, students, users, invoices, and payments. The finance probes exposed and fixed mixed-role unit-scope widening in finance queries.
- [ ] Extend the actor matrix to finance operations beyond invoice/payment reads, assignments, enrollment, grades, and remaining routes; retain per-actor expected statuses and scoped rows.

**R4: Sprint 6a closure**
- [ ] B.1 chart: record approval; implement `seed_chart`, `Account.is_postable`, CashAccount creation from approved custodians; load maps from `docs/`.
- [ ] B.3: confirm triggers on the Neon main database and in CI; add a closed-period test.
- [ ] B.4 receipts (7.7). B.5 fee structures, instalments, invoice-enrollment link, statement PDF (7.8). B.6 v1 finance import mapping (every record gets a unit; duplicate codes reported, not dropped; balances equal v1).
- **Done when:** invoice, pay, refund and reverse flows balance to the cent; the chart loads from the approved CSV; receipts generated at posting and VOID on reversal.

**Sprint 6b: cash custody and institutional finance** (section 7.4). Models and screens: CashAccount management and balances, transfers with two signatures, `FinancePolicy` per unit, petty cash vouchers and drawer counts, disbursements with payee register and limits, expenses and suppliers with receipts (files policy `receipt`), manual daily revenue entry for WCY and WDS, daily float report, approval inbox. Tests: separation of duties, overdraft blocked, thresholds, receipt-required, transfers need both signatures, unit managers see only their drawers, auditor read-only.

**Sprint 6c: reconciliation and close** (section 7.5). Statement importer (idempotent, column-mapping profile, raw file kept), matching engine, classification, worklists, close workflow with unit sign-offs and period lock, reports, auditor workspace, exports. Needs the redacted statement sample first.

**Sprint 7: communications, dashboards, public site (unit-aware).** Real dashboards per role; notifications (approvals waiting, sign-off reminders, unidentified deposits, low float, drawer variances); announcements targetable by unit, department, class; fee reminders from receivable balances (jobs, templates, delivery log); scheduled report emails (monthly unit summary to managers, consolidated to owner); public site per unit with CMS-managed payment instructions (never hard-coded) and apply/enquire routing to the right unit queue; receipts and emails carry the unit name; branding from tokens. Add `comms` app (every model with unit).

**Sprint 8: assistant and appointments (unit-aware).** Knowledge entries and FAQs tagged by unit; appointment slots and booking per unit with transactional booking; handoffs routed to unit managers; public information only, **never fee balances or student records**; eval questions per unit with the harness; WhatsApp webhook with signature verification, Turnstile on the web widget, LLM provider behind an interface with a daily budget guard, retention job for chat data. Add `assistant` app.

**Sprint 9: hardening, parallel run, go-live.** Security review (matrix complete, separation of duties, rate limits, secure headers, `check_revoked` on money endpoints); triggers verified on the production database; backup plus **restore test** including finance tables; two import rehearsals (balances equal v1); **one full parallel month-end** (old process and new system); training (managers, bursar, agent operator, auditor) with one-page job aids; go-live by phase: **Phase A** WTI and WTA fully, WDS and WCY finance-only; **Phase B** WDS features (instructors, vehicles, lesson hours); **Phase C** WCY point of sale.

**Post-launch (order):** driving features, Cyber POS, M-Pesa automation (only after confirming Paybill/Till with Safaricom), allocation engine for HQ costs, pay runs, certificates with QR verification, early-warning dashboard, guardian portal, printed student cards scanned by teachers, SMS reminders, tax e-invoicing if applicable, payroll if wanted.

### 13.3 Gates that apply to every later sprint
Every new feature must answer these before starting: Which unit owns the data (field or exemption)? Which roles by which units may read and write (matrix entries)? What does a student with no account experience? What is appended not edited? What is audited with unit? What are the loading, empty and error states? What does the mobile (390 px) view look like? Where is reference data coming from (approved file, not invented)?

---

## 14. Decisions and inputs still needed from the owner
| Need | For |
|---|---|
| Confirm D9, D12 | Steps 5b, R0.2 |
| Approved chart of accounts (name and date of approver) | R4 |
| Custodians per cash account, opening balances, imprest amounts | 6b |
| Petty-cash thresholds, approval limits, payee list | 6b |
| Redacted M-Pesa agent statement; public use of the agent number; commission treatment; cash-back mechanics | 6c |
| Fee structures per unit and instalment rules | R4 |
| Payment instructions per unit for the website; knowledge content per unit | 7, 8 |
| Three real current registration numbers (to confirm coexistence) | Verified in A5; keep on file |
| Month-end calendar, training schedule | 9 |

---

## 15. Document map

| File | Role |
|---|---|
| `docs/MASTER_GUIDE.md` | This guide: authoritative |
| `docs/PROGRESS.md` | Living tracker (updated every step) |
| `docs/DEVIATIONS.md` | Log of guide-versus-code differences and owner answers |
| `docs/units.md`, `docs/department_unit_map.csv` | Unit seed data and department mapping (reference data) |
| `docs/chart_of_accounts.csv`, `docs/chart_of_accounts_notes.md` | Chart and accountant notes (reference data) |
| `docs/UI_GUIDELINES.md`, `docs/RESOURCE_PAGE_RECIPE.md` | Short UI rules (kept; consistent with section 9) |
| `.github/copilot-instructions.md` | Short standing rules read automatically by Copilot |
| `docs/archive/*` | Blueprint, addendum, remaining sprints, academic plan, Section A, UI plans, Sprint 0: history only |
