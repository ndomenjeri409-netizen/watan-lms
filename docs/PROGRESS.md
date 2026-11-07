# Project Progress Tracker (copy to `docs/PROGRESS.md`)

**Rule for Copilot:** at the end of every step, update this file: change the status, add the date, the commit hash and the test counts. Never tick an item without evidence (a passing test, a query result, or a file path). If a step is interrupted, write what was done and what is left.

Statuses: `DONE` · `IN PROGRESS` · `PENDING` · `BLOCKED (reason)`

## Sprints
| Sprint | Status | Notes |
|---|---|---|
| 0 Foundation | DONE | |
| 0.75 Multi-unit foundation | DONE | |
| 1 to 5 | DONE | Reported complete |
| 6a Finance core | IN PROGRESS | B.2 is complete; accountant approval and B.3 to B.6 remain |
| 6b Cash custody and institutional finance | PENDING | **Starts only after Section A is DONE** |
| 6c Reconciliation and month-end close | PENDING | Needs sample M-Pesa statement |
| 7 Comms, dashboards, public site | PENDING | |
| 8 Assistant and appointments | PENDING | |
| 9 Hardening, parallel run, go-live | PENDING | |

## 6a closure (`REMAINING_SPRINTS_REVISED.md` section B)
| Item | Status | Evidence / notes |
|---|---|---|
| B.1 Chart of accounts approved and seeded | BLOCKED (accountant approval) | Draft: `chart_of_accounts_DRAFT.csv` + notes |
| B.2 Journal engine (balanced entries, unit on lines, idempotency, unique M-Pesa code, maker-checker, balance from journal) | DONE | All five checks are implemented. PostgreSQL CI run [#6](https://github.com/ndomenjeri409-netizen/watan-lms/actions/runs/42227337787) passed 89 tests with `REQUIRE_POSTGRES_TESTS=1` and no skips. Evidence includes `test_payment_is_idempotent_and_mpesa_code_is_globally_unique`, `test_invoice_is_idempotent_and_rejects_key_reuse_for_different_request`, `test_adjustment_and_refund_require_separate_approval`, `test_void_invoice_uses_reversal_and_disallows_bursar_self_approval`, and `test_journal_student_balance_matches_invoices_across_units_and_posting_orders`. M-Pesa codes are normalized in model, admin, and service writes; migration `0007_payment_finance_mpesa_code_normalized.py` adds the normalized-code check and partial unique constraint. The configured Neon `neondb` had no `finance_payment` table at precheck time; no data was altered. |
| B.3 DB guarantees proven in CI | PENDING | Depends on A1 |
| B.4 Receipts (generate at posting, per-unit numbers, VOID on reversal, hash) | PARTIAL | Currently saved on first download |
| B.5 Fee structures per unit, instalments, statements | PENDING | |
| B.6 v1 finance import check | PENDING | |

## Section A remediation (`SECTION_A_REMEDIATION.md`)
| Step | Status | Depends on | Notes |
|---|---|---|---|
| A1 CI proves Postgres tests (`REQUIRE_POSTGRES_TESTS=1`, `@postgres_only`) | DONE | none | CI run [#7](https://github.com/ndomenjeri409-netizen/watan-lms/actions/runs/42228775785): PostgreSQL 16, `REQUIRE_POSTGRES_TESTS=1`, 93 passed, no skips. |
| A2 Guard tests (viewsets scoped, models have unit) | DONE | none | `backend/tests/test_guards.py` guards concrete ModelViewSets, actions, non-model APIViews, and current unit-less models with explicit reasons. Four guard tests pass; direct-unit follow-ups remain listed for A4. |
| A3 Audit log: unit/scope and actor/system label | DONE | D3 | Implementation commit `fdaffe9`; explicit SYSTEM actor labels adopted per D3. GitHub Actions run [#11](https://github.com/ndomenjeri409-netizen/watan-lms/actions/runs/42367403906) passed 101 PostgreSQL tests with no skips; backend and frontend checks passed. |
| A4 Unit ownership on Department, Program, Course, Enrollment, TimetableSlot | PENDING | D2, `docs/department_unit_map.csv` | |
| A5 Per-unit registration numbers | PENDING | D1 | Independent of finance work |
| A6 Authorization matrix coverage | PENDING | A2 to A4 | |

## Decisions pending
| ID | Decision | Owner | Status |
|---|---|---|---|
| D1 | Registration number format (proposal `WTI/ICT/2026/0001`); send sample current numbers | Owner | PENDING |
| D2 | Direct `unit` FK on Program, Course, Enrollment (recommended) vs derived | Owner | PENDING |
| D3 | Audit entries from jobs use a named SYSTEM actor (recommended) | Owner | DONE - A3 uses explicit SYSTEM actor kind and non-empty job labels. |

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
- Date: 2026-11-07
- A2 implementation commit: `6cde587`; `pre-a2` points to the preceding green commit.
- A3 commit `fdaffe9`: `97 passed, 4 PostgreSQL-only skipped, 47 subtests passed` on isolated in-memory SQLite; focused audit tests: `8 passed, 9 subtests passed`. GitHub Actions run [#11](https://github.com/ndomenjeri409-netizen/watan-lms/actions/runs/42367403906) passed 101 PostgreSQL tests with no skips; Ruff, migration check, OpenAPI, frontend lint, API type generation, typecheck, tests, and build passed.
- `backend: pytest -q -rs` with in-memory SQLite: PASS — 89 passed, 4 PostgreSQL-only skipped, 38 subtests passed.
- `backend: ruff check .` and `ruff format --check .`: PASS — 143 files already formatted; migrations excluded.
- `backend: makemigrations --check --dry-run`: PASS — no changes detected.
- OpenAPI generation/validation: PASS — no drift; frontend API type generation and typecheck pass.
- A3 checks: Ruff, format, migration drift, OpenAPI validation, and frontend typecheck pass. The local `DATABASE_URL` points to Neon, so test commands were rerun with in-memory SQLite; do not run local tests against that Neon URL.
- GitHub Actions run [#7](https://github.com/ndomenjeri409-netizen/watan-lms/actions/runs/42228775785): PASS — PostgreSQL 16, `REQUIRE_POSTGRES_TESTS=1`, 93 passed and no skipped tests; frontend lint, generated API type check, typecheck, tests, and build passed.
