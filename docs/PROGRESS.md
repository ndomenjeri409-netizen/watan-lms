# Project Progress Tracker (copy to `docs/PROGRESS.md`)

**Rule for Copilot:** at the end of every step, update this file: change the status, add the date, the commit hash and the test counts. Never tick an item without evidence (a passing test, a query result, or a file path). If a step is interrupted, write what was done and what is left.

Statuses: `DONE` · `IN PROGRESS` · `PENDING` · `BLOCKED (reason)`

## Sprints
| Sprint | Status | Notes |
|---|---|---|
| 0 Foundation | DONE | |
| 0.75 Multi-unit foundation | DONE | |
| 1 to 5 | DONE | Reported complete |
| 6a Finance core | IN PROGRESS | See section "6a closure" |
| 6b Cash custody and institutional finance | PENDING | **Starts only after Section A is DONE** |
| 6c Reconciliation and month-end close | PENDING | Needs sample M-Pesa statement |
| 7 Comms, dashboards, public site | PENDING | |
| 8 Assistant and appointments | PENDING | |
| 9 Hardening, parallel run, go-live | PENDING | |

## 6a closure (`REMAINING_SPRINTS_REVISED.md` section B)
| Item | Status | Evidence / notes |
|---|---|---|
| B.1 Chart of accounts approved and seeded | BLOCKED (accountant approval) | Draft: `chart_of_accounts_DRAFT.csv` + notes |
| B.2 Journal engine (balanced entries, unit on lines, idempotency, unique M-Pesa code, maker-checker, balance from journal) | IN PROGRESS | Invoice idempotency and audit unit attribution implemented. M-Pesa normalization is enforced in `Payment.save()`, admin saves, and `record_payment`; migration `0007_payment_finance_mpesa_code_normalized.py` adds the normalized-code CheckConstraint without a data migration. No payment importer exists. PostgreSQL-only normalized-code and uniqueness tests await CI. Configured Neon `neondb` has no `finance_payment` table, so no existing codes were available to compare; no database data was changed. `test_journal_student_balance_matches_invoices_across_units_and_posting_orders` proves journal and invoice balances match across two units, partial payments, an adjustment, a refund, reversals, and different posting orders. |
| B.3 DB guarantees proven in CI | PENDING | Depends on A1 |
| B.4 Receipts (generate at posting, per-unit numbers, VOID on reversal, hash) | PARTIAL | Currently saved on first download |
| B.5 Fee structures per unit, instalments, statements | PENDING | |
| B.6 v1 finance import check | PENDING | |

## Section A remediation (`SECTION_A_REMEDIATION.md`)
| Step | Status | Depends on | Notes |
|---|---|---|---|
| A1 CI proves Postgres tests (`REQUIRE_POSTGRES_TESTS=1`, `@postgres_only`) | IN PROGRESS | none | Helper and CI skip guard configured; PostgreSQL CI proof remains pending. |
| A2 Guard tests (viewsets scoped, models have unit) | PENDING | none | Run again after B.2 to catch new models |
| A3 Audit log: unit/scope and actor/system label | IN PROGRESS | D3 | Nullable audit unit and centralized unit resolver added; SYSTEM actor handling remains pending. |
| A4 Unit ownership on Department, Program, Course, Enrollment, TimetableSlot | PENDING | D2, `docs/department_unit_map.csv` | |
| A5 Per-unit registration numbers | PENDING | D1 | Independent of finance work |
| A6 Authorization matrix coverage | PENDING | A2 to A4 | |

## Decisions pending
| ID | Decision | Owner | Status |
|---|---|---|---|
| D1 | Registration number format (proposal `WTI/ICT/2026/0001`); send sample current numbers | Owner | PENDING |
| D2 | Direct `unit` FK on Program, Course, Enrollment (recommended) vs derived | Owner | PENDING |
| D3 | Audit entries from jobs use a named SYSTEM actor (recommended) | Owner | PENDING |

## Inputs pending (see `REMAINING_SPRINTS_REVISED.md`, "Inputs you need to provide")
- Approved chart of accounts (accountant)
- Fee structures per unit
- Cash account custodians and opening balances
- Drawer imprest amounts, petty cash thresholds and categories
- Approval thresholds and daily limits
- Teacher and worker payee list
- Redacted M-Pesa agent statement; answers on public use, commission and cash-back mechanics

## Working agreements
- Work sequentially: do not run Section A and Section B work on parallel branches that both add migrations to the same app.
- Tag a known-good commit before each step (`git tag pre-<step>`), and commit each step separately.
- Every new model has a `unit` (or an exemption with a reason), every new endpoint has role x unit tests, every Postgres-only test uses `@postgres_only`.
- Never invent finance reference data (accounts, thresholds, categories, payees, amounts).

## Latest verification
- Date: 2026-11-06
- HEAD: `e905def4165c4f2c3fde3403cd9946b8c359cf75` (worktree changes uncommitted)
- `backend: ruff check .`: PASS
- `backend: ruff format .`: PASS — 142 files unchanged; migrations excluded.
- `backend: ruff format --check .`: PASS (142 files already formatted; migrations excluded).
- `backend: pytest -q -rs` with in-memory SQLite: PASS — 85 passed, 4 PostgreSQL-only skipped, 38 subtests passed. PostgreSQL constraint tests are not exercised locally.
- `backend: makemigrations --check --dry-run`: PASS (no changes detected; constraint migration generated).
- `backend: pytest -rs` with the configured PostgreSQL connection: BLOCKED — test database migration setup fails in `apps/finance/migrations/0002_journal_guards.py`; Psycopg treats an unescaped `%` in the migration SQL as an incomplete placeholder.
- Earlier checks: `makemigrations --check --dry-run`, OpenAPI validation, frontend typecheck, and Finance page tests passed (4 Finance tests).
- Duplicate-code precheck: configured Neon `watan_lms` / `neondb` has no `finance_payment` relation or payment-named table; no data was altered.
