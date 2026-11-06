# Section A Remediation — closing the six audit gaps

Input: Copilot's Section A audit report (no code changed; focused tests pass on SQLite). All six checks reported "Fail", but they are **not equally serious**, and two items are decisions rather than bugs. This file orders the fixes and says what to decide first.

## Triage

| # | Gap | Type | Severity | Fix order |
|---|---|---|---|---|
| 6 | Postgres trigger tests can be skipped in CI | Process gap | **High** (finance integrity proof) | 1 |
| 2 | No guard test for unscoped viewsets | Missing test | **High**, cheap | 2 |
| 4 | `AuditLog` has no unit; actor nullable | Data model | **High** (audit trail) | 3 |
| 1 | `Department.unit` nullable; `TimetableSlot` has no unit; Program/Course/Enrollment derive unit indirectly | Data model + decision | **High** | 4 |
| 3 | Registration sequence is department-keyed, no unit prefix | Decision + data model | Medium | 5 |
| 5 | Authorization matrix covers only selected resources | Missing tests | **High**, largest | 6 |

**Not failures yet:** "No Announcement or appointment model found" is expected, since those arrive in Sprints 7 and 8. The guard in A1 makes sure they get a unit when they are built.

**Decisions needed from you before the steps that depend on them**
- **D1 (needed for A5):** registration number format. Proposal: `{UNIT}/{DEPT}/{YEAR}/{SEQ}` such as `WTI/ICT/2026/0001`, and `{UNIT}/{YEAR}/{SEQ}` for units without departments (for example `WDS/2026/0001`). **Existing numbers stay as issued** (never renumber). Please send two or three real current numbers so the new format can coexist with them.
- **D2 (needed for A4):** direct vs indirect unit on Program, Course, Enrollment. Recommendation: **add a direct, non-null `unit` FK** to Department, Program, Course, Enrollment and TimetableSlot, with a consistency check against the parent. Reason: simpler and faster scoping, simpler finance reports, and a database-level safety net. The alternative (keep deriving unit through joins) works with `unit_field = "program__department__unit"` paths but is easier to get wrong.
- **D3 (needed for A3):** system-generated audit actions (jobs, imports). Recommendation: allow them with an explicit `SYSTEM` actor kind, never a silent null.

## Rules for Copilot
1. One step at a time; stop after each step with the check result.
2. Migrations must be reversible where practical, and data migrations must **fail loudly** on anything they can't map. Never guess a unit.
3. Don't change behaviour outside the step.
4. Run `pytest`, `ruff`, `makemigrations --check`, and regenerate OpenAPI after every step.

---

## A1. CI proves the Postgres tests (item 6)

Why first: the finance triggers (append-only, balanced entries, closed periods) are your integrity guarantee. A skipped test proves nothing.

- [x] Add a helper in `tests/helpers.py`:
```python
import os, unittest
from django.db import connection

REQUIRE_PG = os.environ.get("REQUIRE_POSTGRES_TESTS") == "1"

def postgres_only(test):
    """Skip locally on SQLite; in CI (REQUIRE_POSTGRES_TESTS=1) never skip, and fail if the DB is not Postgres."""
    if REQUIRE_PG:
        def wrapper(*a, **kw):
            assert connection.vendor == "postgresql", "REQUIRE_POSTGRES_TESTS=1 but the database is not PostgreSQL"
            return test(*a, **kw)
        wrapper.__name__ = test.__name__
        wrapper.__doc__ = test.__doc__
        return wrapper
    return unittest.skipUnless(connection.vendor == "postgresql", "PostgreSQL only")(test)
```
- [x] Replace every `skipUnless(...postgresql...)` in the finance trigger tests with `@postgres_only`.
- [x] In `.github/workflows/ci.yml`, set `REQUIRE_POSTGRES_TESTS: "1"` in the backend job `env`, and run `pytest -rs` so any skip is printed.
- [x] Add a CI step that fails if any test was skipped in CI: `pytest -rs | tee out.txt; ! grep -q "SKIPPED" out.txt`.
- [ ] Optional local run: `docker compose up -d db` (the Sprint 0 compose file already has Postgres 16), then set `DATABASE_URL` to it and `REQUIRE_POSTGRES_TESTS=1`. If Docker isn't installed, rely on CI. Never run tests against the production Neon database; use a separate test project or branch.

**Check:** CI shows the two trigger tests as **passed**, not skipped; temporarily pointing CI at SQLite makes them **fail**.

---

## A2. Guard tests for scoping and unit ownership (items 1 and 2)

- [x] **Viewset guard** `tests/test_guards.py`: collect every concrete `ModelViewSet` subclass (recursively) and assert it inherits `ScopedViewSetMixin` and its queryset model has a manager whose queryset implements `for_user`.
```python
from rest_framework.viewsets import ModelViewSet
from common.scoping import ScopedViewSetMixin

def all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from all_subclasses(sub)

def test_every_model_viewset_is_scoped():
    import apps.accounts.urls, config.urls  # ensure modules are imported
    offenders = [v.__name__ for v in all_subclasses(ModelViewSet)
                 if not v.__module__.startswith("rest_framework") and not issubclass(v, ScopedViewSetMixin)]
    assert offenders == [], f"Unscoped viewsets: {offenders}"
```
- [x] **Non-model views:** also assert that every `APIView`/`@action` either calls a scoped queryset or is listed in an explicit allow-list with a reason (for example `MeView`, health checks). Keep the allow-list in the test file.
- [x] **Model guard:** every concrete model in the unit-owned apps must have a `unit` field **or** be listed in `UNIT_EXEMPT` with a reason (User, BusinessUnit, Student person record, group settings, and so on). Adding a model without either fails the build.
```python
from django.apps import apps
UNIT_EXEMPT = {"accounts.User": "group-level identity", "org.BusinessUnit": "is the unit",
               # add with a reason; reviewed in code review
              }
def test_every_model_has_unit_or_is_exempt():
    missing = [m._meta.label for m in apps.get_models()
               if m._meta.app_label in {"org","academics","people","enrollment","scheduling","attendance","assessment","finance","comms","assistant","files","audit"}
               and not any(f.name == "unit" for f in m._meta.get_fields())
               and m._meta.label not in UNIT_EXEMPT]
    assert missing == [], f"Models without unit or exemption: {missing}"
```
(The first run will list real gaps; that list feeds A4. Add the exemptions that are genuinely group-level, each with a reason.)

**Check:** both guards pass; a newly discovered unscoped viewset, unaccounted action/APIView, or unit-less model fails the guard until it is scoped or explicitly reasoned.

Evidence: `backend/tests/test_guards.py`; all four guard tests pass. Unit-less models are explicitly reasoned, including models scheduled for direct unit ownership in A4.

---

## A3. Audit trail integrity (item 4)

- [x] Add to `AuditLog`: `unit` (FK to BusinessUnit, nullable), `scope` (`UNIT` or `GROUP`), `actor_kind` (`USER` or `SYSTEM`), `actor_label`, and `meta`.
- [x] Constraints:
  - `scope = UNIT` requires `unit` not null; `scope = GROUP` requires `unit` null.
  - `actor_kind = USER` requires `actor` not null; `SYSTEM` requires `actor` null and a non-empty `actor_label` (job name).
- [x] `record_audit(actor, action, obj, *, unit=None, group_level=False, before=None, after=None)`:
  - Derive `unit` from `obj.unit` when present; otherwise require the caller to pass `unit` **or** `group_level=True`. Raise if neither (no silent nulls).
  - Require an actor or an explicit `system_label`.
- [x] Update every existing `record_audit` call to satisfy the new signature, including public application submissions.
- [x] **Backfill** existing rows: derive `unit` from the target object where it still exists; rows you cannot attribute become `scope=GROUP` with a note in a `meta` field, never a guessed unit. Print a summary (counts attributed, counts left group-level).
- [x] Index `(unit, created_at)` and `(actor, created_at)`.
- [x] Scoping: `AuditLog.objects.for_user(user)`: unit managers see rows for their units; `GROUP` rows and all rows only for `SUPER_ADMIN`, `ADMIN`, `DIRECTOR`, `AUDITOR`. The audit log stays append-only.
- [x] Tests: raises when unit and group flag are both missing; constraint tests for the four combinations; scoping tests per role; backfill test on sample rows (`backend/tests/test_audit.py`).

**Check:** locally verified with 8 focused tests and the full SQLite suite; PostgreSQL CI verification is pending.

---

## A4. Unit ownership on data (item 1)

Prerequisite: D2 confirmed.

- [ ] **Department:** make `unit` non-null. Data migration with an explicit mapping file `docs/department_unit_map.csv` (code to unit code). Expected from your data: BFS, ICT, LEK, T&T to `WTI`; GDS to `WTA`. **If any department is unmapped the migration fails**; it never defaults.
- [ ] **Program, Course, Enrollment, TimetableSlot:** add a direct non-null `unit` FK, backfilled from the parent (Course/Program from Department, Enrollment from Course, TimetableSlot from its Course/Class).
- [ ] **Consistency:** validate on save and in the service layer that `child.unit == parent.unit` (for example Course.unit equals Department.unit; Enrollment.unit equals Course.unit); add a DB trigger or check where simple; add tests that mismatches are rejected.
- [ ] Switch each model's queryset to `UnitScopedQuerySet` with `unit_field = "unit"` (direct field).
- [ ] Update serializers so `unit` is read-only on children (derived), writable only on Department creation.
- [ ] Re-run the A2 model guard until it passes; remove any exemption that was only a placeholder.
- [ ] Regenerate OpenAPI and frontend types; fix the UI where unit is now required (Departments drawer already has a unit field).
- [ ] Confirm with a SQL query before and after: row counts per unit match expectations; no rows with null unit.

**Check:** zero rows with null unit; mismatch tests pass; A2 model guard passes.

---

## A5. Per-unit registration numbers (item 3)

Prerequisite: D1 confirmed.

- [ ] Rework the sequence table:
```python
class RegistrationSequence(models.Model):
    unit = models.ForeignKey("org.BusinessUnit", on_delete=models.PROTECT)
    department = models.ForeignKey("org.Department", null=True, blank=True, on_delete=models.PROTECT)
    year = models.PositiveSmallIntegerField()
    next_number = models.PositiveIntegerField(default=1)
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["unit", "department", "year"], condition=models.Q(department__isnull=False), name="uniq_regseq_dept"),
            models.UniqueConstraint(fields=["unit", "year"], condition=models.Q(department__isnull=True), name="uniq_regseq_unit"),
        ]
```
- [ ] One function `format_registration_number(unit, department, year, seq)` builds the number per D1 (the single place the format lives).
- [ ] Allocation stays atomic (`transaction.atomic` + `select_for_update`; create the row first with `get_or_create`, then lock).
- [ ] `Student.registration_number` is **unique across the whole business** and immutable once issued.
- [ ] **Migration:** keep every existing number unchanged. Map each existing sequence row to its unit through its department, set `next_number` to the highest existing sequence for that key plus one. A report lists any number that doesn't parse (do not fix automatically).
- [ ] Tests: concurrent allocation produces distinct numbers; units without departments use the unit-level sequence; existing numbers are untouched; the formatter output matches D1.

**Check:** two simultaneous enrolments never get the same number; old numbers still resolve.

---

## A6. Authorization matrix coverage (item 5)

Largest step; do it last so it exercises everything fixed above. Build it **generated from the code**, not hand-written.

- [ ] **Endpoint inventory:** a test helper walks the DRF router/URL conf and lists every `(basename, action)` (list, retrieve, create, update, partial_update, destroy, and each `@action`).
- [ ] **Matrix data file** `tests/authz_matrix.yaml`: for each endpoint, the expected result (`allow`, `deny`, `own_unit_only`, `self_only`) for each actor profile: anonymous, awaiting approval (no assignments), `SUPER_ADMIN`, `ADMIN`, `DIRECTOR`, `AUDITOR`, `UNIT_MANAGER` (own unit and other unit), `HOD`, `TEACHER`, `BURSAR` (unit-scoped and group-wide), `CASHIER`, `STUDENT` (self and other).
- [ ] **Coverage test:** fails if any endpoint from the inventory has no entry in the matrix (so new endpoints cannot ship untested).
- [ ] **Parametrized test:** builds fixtures (units A and B, one user per profile, sample objects in each unit), calls each endpoint as each profile, and asserts the expected status (200/201/204 vs 403/404) and, for scoped lists, that only permitted rows come back.
- [ ] **Priority order within the matrix:** finance (invoices, payments, receipts, journal), users and assignments, enrollment, grades, then the rest.
- [ ] **Read-only roles:** assert `DIRECTOR` and `AUDITOR` get 403 on every write.
- [ ] Port any remaining cases from the old `firestore.rules.test.ts` that aren't covered.

**Check:** the coverage test passes; adding a new route without a matrix entry fails CI.

---

## Definition of done for Section A
- [ ] CI shows the Postgres trigger tests passing; skips fail CI.
- [ ] Guard tests for scoped viewsets and unit-bearing models pass.
- [ ] Audit rows always have an actor or system label, and an explicit scope.
- [ ] No data row without a unit; parent/child unit consistency enforced.
- [ ] Registration numbers are per unit, atomic, unique, and old numbers untouched.
- [ ] The authorization matrix covers every endpoint and role profile.

Then continue with Sprint 6b.

## Prompts for Copilot (agent mode), one at a time
```
Read docs/SECTION_A_REMEDIATION.md, step A1 only. Implement it exactly. Run the Check, show
the result, and stop.
```
Repeat for A2, A3, A4 (after D2), A5 (after D1), A6.
