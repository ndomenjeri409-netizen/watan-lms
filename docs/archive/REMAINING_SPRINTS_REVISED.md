> SUPERSEDED by MASTER_GUIDE.md; do not follow.

# Remaining Sprints (6a closure to launch), revised for multi-unit finance

Replaces Sprints 6 to 9 and "After launch" in `WATAN_LMS_V2_BLUEPRINT.md`. Read with `MULTI_UNIT_AND_FINANCE_ADDENDUM.md` (section numbers below refer to it). Sprints 0 to 5 are assumed done; section A lists a short audit to confirm they follow the unit rules.

## Rules for Copilot
1. One sprint at a time; one step at a time; stop after each step with the check result and wait.
2. Every new table carries `unit` (cost centre) where it belongs; every list endpoint uses the unit-scoped queryset; every posting writes balanced journal lines with `unit` on each line.
3. **Never invent finance reference data** (chart of accounts, thresholds, categories, payee lists, fee amounts). Load them only from approved files in `docs/` (CSV/MD). If a file is missing, stop and ask.
4. No hard-coded colours (palette rules in `UI_POLISH_PASS_1.md`); no fake numbers in the UI.
5. Money, journal, receipts and audit are append-only; corrections are reversals with a reason.

---

## What changed, at a glance

| Sprint | Original plan | Now |
|---|---|---|
| **6a** Finance core | Fees, invoices, payments, ledger, receipts | **Close out** (section B): approved chart of accounts, journal engine verified, unique M-Pesa codes, Postgres triggers proven in CI, receipt integrity |
| **6b** (new) | Not in original | **Cash custody and institutional finance:** drawers, M-Pesa agent float, petty cash, disbursements to teachers/workers, expenses, transfers, daily revenue entry |
| **6c** (new) | Not in original | **Reconciliation and month-end close:** statement import, matching, classification, unit sign-offs, period lock, consolidated and custody reports, auditor workspace |
| **7** | Comms, reports, public site | **Unit-aware** dashboards, approval notifications, fee reminders, per-unit public pages and payment instructions |
| **8** | Assistant and appointments | **Unit-aware** assistant, knowledge and appointment slots per unit; no balance disclosure |
| **9** | Hardening and launch | Adds finance hardening, **parallel-run month-end**, training, and **phased go-live** (Phase A then B then C) |
| **After launch** | M-Pesa automation etc. | Re-ordered; M-Pesa automation depends on whether you get a Paybill/Till |

---

## A. Quick audit of earlier sprints (do once, before 6b)

Ask Copilot to run these checks and report; fix gaps in small commits.
- [ ] Every model that belongs to a unit has a non-null `unit` FK: Department, Program, Course, Enrollment, FeeStructure, Invoice, Announcement (if unit-targeted), Appointment slots, Student registration sequences.
- [x] Every `ModelViewSet` uses the unit-scoped queryset/mixin; a test fails the build if one doesn't.
- [ ] Registration numbers use a **per-unit** sequence and the unit code prefix (atomic, `select_for_update`).
- [ ] Audit log rows carry `unit` (nullable for group actions) and actor.
- [ ] The authorization matrix covers role × unit × resource × action for all existing resources.
- [x] CI runs the PostgreSQL job with `REQUIRE_POSTGRES_TESTS=1` so Postgres-only tests **fail instead of skip** in CI (see B.3).

---

## B. Sprint 6a closure (finance core)

What is done (per your report): `/app/finance` with student-scoped history, Bursar invoice issuance and payment recording, authenticated receipt downloads, receipt PDFs saved to object storage, corrected API contracts, tests passing.

What remains. **Tick a box only if the code already does it; otherwise build it.**

### B.1 Chart of accounts (blocker)
- [ ] Get the chart **approved by your accountant** (a draft proposal can be prepared for them to edit).
- [ ] Store it as `docs/chart_of_accounts.csv` (code, name, type, parent, is_cash) and load it with an idempotent `seed_chart` command or data migration. One shared chart for the whole business; units are a dimension on lines, not separate charts.
- [ ] Until approved: fee structures and real invoices stay disabled in production (a settings flag), but development continues with test fixtures.

### B.2 Journal engine
- [x] Invoice, payment, refund, adjustment (waiver) and reversal each post a **balanced** entry; every line has `unit`; cash lines have `cash_account`.
- [x] Idempotency key on payment and invoice endpoints (retry never double-posts).
- [x] **M-Pesa transaction code unique across the whole business:** normalize (trim, uppercase) and enforce with a partial unique DB constraint across all payments.
- [x] Maker-checker on refunds, waivers and voids, with a mandatory reason.
- [x] Student balance computed from the journal (receivable lines for the student) and equal to invoice-level balances; a test proves it.

### B.3 Database guarantees proven in CI
- [ ] Triggers: journal entries/lines and payments are append-only; entries must balance at commit; posting into a closed period is rejected.
- [ ] The Postgres-only tests run in CI against PostgreSQL 16. Add `REQUIRE_POSTGRES_TESTS=1` so a skipped test fails the CI job. Locally they may skip.
- [ ] After merging, run the migration once on the Neon staging database and rerun the trigger tests there.

### B.4 Receipts (integrity detail)
- [ ] Generate the receipt PDF **when the payment posts** (background job), not on first download, so an audit copy always exists; the download just fetches it.
- [ ] Receipt numbers are sequential **per unit** (counter row with a lock); document any allowed gaps.
- [ ] Receipts show the unit, student, invoice, amount, channel, M-Pesa code and issuer.
- [ ] If a payment is reversed, the original receipt is marked **VOID** (new stored version with a visible watermark), and the reversal is referenced.
- [ ] Store a content hash with each receipt so tampering is detectable.

### B.5 Fee structures and statements
- [ ] Fee structures per unit and course/program, with instalment plans and due dates.
- [ ] Student statement (invoices, payments, balance) downloadable as PDF.
- [ ] Finance screens respect the unit switcher; Bursars with a group-wide assignment can view all units.

### B.6 Import from v1
- [ ] Re-check the finance part of the v1 import (blueprint section 14): every invoice and payment gets a unit, M-Pesa codes are preserved, duplicate codes are reported (not dropped), and balances equal v1's.

**Done when:** invoice, pay, refund and reverse flows balance to the cent; trigger tests pass in CI; chart of accounts is loaded from the approved file; receipts are generated at posting and VOID on reversal.

---

## C. Sprint 6b — Cash custody and institutional finance (addendum 4A.1 to 4A.4)

Inputs needed first: approved chart (expense categories), drawer imprest amounts, petty-cash thresholds and categories, approval thresholds, named custodians, payee list (teachers and workers with verified phone numbers).

- [ ] **Cash accounts:** `CashAccount` (drawers per unit, the shared M-Pesa agent float held by WCY, bank if any) with custodian and opening balances; admin screen "Cash and custody" showing balances per account.
- [ ] **Transfers** between cash accounts (drawer to float, float to drawer, bank): two signatures (sender and receiver), reference, journal entry.
- [ ] **Petty cash:** `FinancePolicy` per unit (imprest limit, receipt-required threshold, countersign threshold, categories). Vouchers (`TEA_LUNCH`, `EMERGENCY`, `TRANSPORT`, `SUPPLIES`, `OTHER`) post expense against the drawer; overdrawing is blocked; emergencies flagged for next-day review; receipts uploaded through the `files` app (`purpose=receipt`).
- [ ] **Daily drawer count:** expected vs counted, variance and explanation; repeated variances flagged to the group admin.
- [ ] **Disbursements to teachers and workers from the agent float:** states `REQUESTED → APPROVED → EXECUTED → RECONCILED` (or `REJECTED`); requester = manager of the cost-centre unit; approver = `ADMIN`/`SUPER_ADMIN` (never the requester or executor); executor = the agent-number operator, who records the M-Pesa code; per-payee and daily limits; approval inbox.
- [ ] **Payee register:** verified phone numbers; changes need approval.
- [ ] **Daily float report:** opening, in, out, closing for the custodian and approver.
- [ ] **Expenses and suppliers:** expense with category, unit, supplier (optional), receipt; paid at once or on credit (payable); supplier payments.
- [ ] **Manual daily revenue entry** for WCY (services) and WDS: totals by service category and channel (cash or M-Pesa) posting to the journal, with the day's drawer count attached.
- [ ] Frontend (new pages, using the shell and palette): **Cash and custody**, **Petty cash**, **Disbursements** (requests, approvals, execution), **Expenses**, **Daily revenue**, **Drawer count**. Each page follows the list-page recipe.
- [ ] Tests: separation of duties (requester ≠ approver ≠ executor), overdraft blocked, thresholds enforced, receipt required above threshold, transfers need both signatures, unit managers see only their unit's drawers and vouchers, auditor read-only.

**Done when:** a teacher payment goes request → approval → execution (with code) and appears in the float and unit reports; petty cash and drawer counts work with the real thresholds; every posting is unit-attributed and audited.

---

## D. Sprint 6c — Reconciliation and month-end close (addendum 4A.5 to 4A.7)

Inputs needed first: a redacted sample of the M-Pesa agent statement, answers to the open questions (public use of the agent number, commission treatment, cash-back mechanics).

- [ ] **Statement importer:** CSV (or the export format your sample shows) with a stored column-mapping profile; idempotent (re-importing never duplicates lines); keeps the raw file via the `files` app.
- [ ] **Matching engine:** exact match by M-Pesa code; suggested matches by amount, time window and payer phone; manual match and unmatch with audit.
- [ ] **Classification:** `STUDENT_FEE`, `STAFF_DISBURSEMENT`, `CYBER_SERVICE_SALE`, `PUBLIC_AGENT_TXN` (pass-through, not income), `FLOAT_TOPUP_OR_TRANSFER`, `COMMISSION`, `CHARGES`, `UNKNOWN`. `UNKNOWN` lines block close. Commission and charges post to the designated accounts and cost centre.
- [ ] **Worklists:** unidentified deposits, recorded payments with no statement line, unmatched disbursements.
- [ ] **Month-end close workflow:** drawer counts signed → statement imported and matched → exceptions resolved → unit month summaries → **unit sign-offs** (`UnitPeriodSignoff`) → group approval and **period lock** → auditor review.
- [ ] **Reports:** unit month summary (opening, collections by channel, expenses, petty cash, disbursements on behalf, closing); consolidated by unit side by side; **custody report**; **settlement position by unit**; receivables ageing; collections by day and channel.
- [ ] **Auditor workspace:** read-only journal explorer with drill-down (report line → entry → source document → receipt); exports (CSV/PDF) are logged.
- [ ] Reports are database aggregates, not client-side sums; indexes added for date, unit and account filters.
- [ ] Tests: importer idempotency, matching rules, `UNKNOWN` blocks close, closed periods reject postings, sign-off order enforced, report totals equal journal totals.

**Done when:** a real month's statement imports, reconciles with explained exceptions, all units sign off, the period locks, and the auditor can trace any report figure to a receipt.

---

## E. Sprint 7 — Communications, dashboards and public site (unit-aware)

- [ ] **Dashboards from real data:** unit manager (collections by channel, overdue, drawer and float balances, pending approvals), Bursar (unreconciled items, today's receipts), Director/Auditor (consolidated KPIs, trends), Teacher and Student as planned. Cards come from `reports/overview` keys; none show placeholders.
- [ ] **Notifications:** approvals waiting (disbursements, refunds), sign-off reminders, unidentified deposits, low float, drawer variances, closed-period attempts. In-app inbox first; email next.
- [ ] **Announcements** targetable by unit, department, class.
- [ ] **Fee reminders (dunning)** from receivable balances: scheduled jobs, templates, delivery log, per-unit schedules.
- [ ] **Scheduled report emails:** monthly unit summary to each manager, consolidated summary to the owner/director.
- [ ] **Public site per unit:** WTI courses and departments, WTA GDS courses, WDS driving courses and packages, WCY services. Payment instructions (agent number, accepted channels) come from **CMS/settings per unit**, never hard-coded. Apply/enquire forms route to the right unit's admissions queue.
- [ ] Receipts, statements and emails carry the unit name; branding follows the palette tokens.

**Done when:** each role's home screen uses real, unit-scoped data; managers receive their approval and sign-off notifications; the public site presents the four units with CMS-managed payment instructions.

---

## F. Sprint 8 — Assistant and appointments (unit-aware)

- [ ] Knowledge entries, intents and FAQs are **tagged by unit**; the assistant detects or asks which unit the visitor means, and answers only from that unit's content.
- [ ] Appointment slots and booking per unit (and per resource later: instructor, lab); handoffs route to the right unit manager.
- [ ] Payment instructions in answers come from the same CMS/settings as the public site.
- [ ] **Privacy rule:** the assistant gives public information only. It does **not** disclose fee balances or student records. (A verified, authenticated balance enquiry can be a later feature.)
- [ ] Eval questions per unit; the harness reports pass rates per unit and must not regress against v1.
- [ ] WhatsApp webhook with signature verification; Turnstile on the web widget; Gemini behind a provider interface with a daily budget guard; retention job for chat data.

**Done when:** eval pass rates meet v1's per unit, bookings land in the right unit's calendar, and no private finance data is ever returned.

---

## G. Sprint 9 — Hardening, parallel run and phased go-live

- [ ] **Security review:** authorization matrix complete for every finance endpoint (role × unit); separation-of-duties tests; rate limits; secure headers; `check_revoked` on money endpoints; secrets audit.
- [ ] **Database:** triggers verified on the production database; Neon backups plus weekly `pg_dump` via GitHub Actions; a **restore test** that includes finance tables; size and index review for journal tables.
- [ ] **Data import rehearsals:** twice on staging; finance totals and every student's balance must equal v1.
- [ ] **Parallel run:** operate one full month end with both the current process (manual reconciliation) and the new system; compare unit summaries and cash positions; fix differences before cutover.
- [ ] **Training:** short sessions for unit managers (approvals, petty cash, sign-off), bursar (payments, receipts, reconciliation), cashier/agent operator (disbursement execution), auditor (workspace). Provide one-page job aids.
- [ ] **Go-live by phase:**
  - **Phase A:** WTI and WTA fully (LMS and finance); WDS and WCY on finance-only (daily revenue and expense posting) so the owner sees all four units in the consolidated audit from day one.
  - **Phase B:** WDS features (instructors, vehicles, lesson hours).
  - **Phase C:** WCY point-of-sale.
- [ ] Go-live checklist (blueprint Appendix B plus: chart of accounts approved and loaded, thresholds configured, custodians named, payee register verified, first month-end calendar agreed).

**Done when:** a full parallel month reconciles, training is done, backups restore cleanly, and Phase A is live.

---

## H. After launch (re-ordered)

1. **Driving School features** (Phase B), then **Cyber POS** (Phase C).
2. **M-Pesa automation:** only after confirming with Safaricom what your number supports. Daraja callbacks generally need a Paybill or Till; otherwise keep statement import.
3. Allocation engine for `HQ` shared costs; pay runs for teachers (batches, not payroll maths); payroll later if wanted.
4. Certificates with QR verification; admissions pipeline enhancements; early-warning dashboard; parent/guardian portal.
5. Tax invoicing/e-invoicing integration if your accountant says it applies.

---

## Inputs you need to provide (and when)

| Input | Needed by | Who |
|---|---|---|
| Approved chart of accounts (CSV) | 6a closure | Accountant |
| Fee structures per unit, instalment rules | 6a closure / launch | Unit managers |
| Drawer imprest amounts, petty-cash categories and thresholds | 6b | Owner and unit managers |
| Approval thresholds, daily float/payee limits, named custodians | 6b | Owner |
| Teacher and worker payee list with verified phone numbers | 6b | Admin |
| Redacted M-Pesa agent statement sample; answers on public use, commission, cash-back mechanics | 6c | Cyber manager |
| Payment instructions per unit for the website | 7 | Unit managers |
| Knowledge content per unit for the assistant | 8 | Unit managers |
| Training schedule and month-end calendar | 9 | Owner |

## Prompts for Copilot (agent mode)

Audit first:
```
Read docs/REMAINING_SPRINTS_REVISED.md section A. Run each check against the repository and
report which pass and which fail. Do not change code yet. Stop after the report.
```
Then for each step:
```
Read docs/REMAINING_SPRINTS_REVISED.md section B.2 and docs/MULTI_UNIT_AND_FINANCE_ADDENDUM.md
sections 4.1 to 4.3. Verify each item against the current code and tick only what already
exists. Implement the missing items one at a time. Do not invent finance reference data.
Run the checks, show results, and stop.
```
