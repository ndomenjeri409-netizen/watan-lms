> SUPERSEDED by MASTER_GUIDE.md; do not follow.

# Addendum — Four Business Units, Institutional Finance and Consolidated Audit

Amends `WATAN_LMS_V2_BLUEPRINT.md`. Where the two disagree, **this addendum wins**.

**Decisions recorded (Nov 2026):** the four units are **cost centres of one business**, not separate legal entities · unit codes are **`WTI`, `WTA`, `WDS`, `WCY`** (plus `HQ` for shared items) · the new roles `UNIT_MANAGER`, `AUDITOR`, `CASHIER` are confirmed · **WCY (Cyber) holds the institution's M-Pesa agent number**, which receives student fees for the other units and pays teachers and workers · unit managers run **cash drawers** and pay petty expenses from them · units **reconcile cash flow at month end**.

## 0. The answer in brief

1. **Don't treat the four entities as four separate systems, and don't make their managers global Admins.** Model them as **Business Units** inside one system, one database and one login. Managers get a **unit-scoped role**; a small group of people get **cross-unit** roles (owner, director, auditor). This is what makes consolidated revenue auditing possible.
2. **Finance changes the most.** It grows from "student fees" into a small **double-entry accounting core** (income, expenses, cash accounts) that every unit posts to. That core is what the audit runs on. Because the units are cost centres of one business and share one M-Pesa agent account, it also needs **cash-account custody, petty-cash drawers and a month-end reconciliation workflow** (section 4A).
3. **Don't "finish and upgrade later" for the foundation. Do finish the UI polish and defer the features.**
   - **Do now (cheap now, expensive later):** the unit dimension on data, unit-scoped roles, scoped queries, the shape of the ledger, per-unit numbering and the unit switcher. Today only the user table exists, so changing it costs days; after Sprint 1 to 3 it touches every table, query, permission test and report, and requires back-filling real data.
   - **Defer:** Cyber point-of-sale, driving-school lesson/vehicle scheduling, expense allocation engine, bank reconciliation imports, payroll, tax-invoice integrations, M-Pesa automation.
4. **New step before Sprint 1: Sprint 0.75 "Multi-unit foundation"** (section 7), about a week.

---

## 1. What each unit needs

| Unit | Kind | Learners? | Needs beyond the LMS core | Finance shape |
|---|---|---|---|---|
| **Watan Institute (WTI)** | Academic | Yes | Departments (ICT, Business, Tourism, Languages…), programs, courses, timetable, grades | Term fees, invoices, instalments, receipts |
| **Watan Travel Agency (WTA), GDS training** | Training centre | Yes | Course levels (Amadeus L1/L2, Travelport L1/L2), certificates, lab capacity | Per-course fees, often shorter cohorts |
| **Watan Driving School (WDS), NTSA courses** | Driving | Yes | Instructor and vehicle scheduling, lesson hours, test bookings, compliance records | Package fees, extra lessons, test fees, fuel/vehicle costs |
| **Watan Cyber (WCY)** | Services | Mostly walk-in customers | Service catalogue, quick sales, daily cash-up | Many small cash/M-Pesa sales, consumables costs |

Observation: **the first two are almost exactly the existing LMS model** with a unit label. Driving adds resource scheduling. Cyber is closer to point-of-sale than to an LMS. Phase delivery accordingly (section 6).

Note from your current data: the department "IATA Global Distribution Systems (GDS)" belongs to **Watan Travel Agency**, not the Institute. The v1 import must map each department to a unit.

---

## 2. Architecture change: Business Unit as a first-class dimension

**One database, one Firebase login, one `Student`/person identity, with `unit` on everything that belongs to a unit.** Not four databases or four deployments, because consolidated reporting and shared people (a student may take a GDS course and a driving course) need one place.

```
BusinessUnit ──< Department ──< Program/Course
     │                              │
     ├──< Enrollment ───────────────┘
     ├──< FeeStructure ──< Invoice ──< (journal postings)
     ├──< Expense, Supplier, CashAccount
     └──< RoleAssignment (user, role, unit)
```

`BusinessUnit(code, name, kind, currency, modules, is_active)`:
- `kind` in `ACADEMIC | TRAINING | DRIVING | SERVICES | GROUP` (`GROUP` is only for the `HQ` shared cost centre).
- `modules` is a per-unit switch list (for example `{"lms": true, "attendance": true, "pos": false}`), so Cyber can have no LMS screens and the Institute no POS.
- Codes (**confirmed**): `WTI`, `WTA`, `WDS`, `WCY`, plus `HQ` for shared items. Names are seeded from `docs/units.md` (copy `units.md` from the outputs folder).
- A pseudo-unit **`HQ` / Group** holds shared costs (rent, utilities, shared salaries) until allocation rules exist.

**Unit-owned tables** carry a non-null `unit` FK (denormalized for fast scoping): Department, Program, Course, Enrollment, FeeStructure, Invoice, Payment/Journal entries, Expense, Supplier (or group-level), CashAccount, Announcement (optional), AuditLog (nullable). **Group-level tables** have no unit: User, Student (person), Firebase identity, system settings.

**Registration numbers** are per unit (and per department/year where applicable) with a unit prefix; each unit has its own atomic sequence.

---

## 3. Roles and access

### 3.1 Roles (revises the locked list; **please confirm**)
| Role | Scope | Can do |
|---|---|---|
| `SUPER_ADMIN` | Group | Everything, including units, roles, settings |
| `ADMIN` | Group | Operational admin across units (no role escalation to SUPER_ADMIN) |
| `DIRECTOR` | Group | Read-only dashboards and reports across all units |
| **`AUDITOR`** (new) | Group | Read-only access to finance, journal, audit log and exports across all units; cannot change anything |
| **`UNIT_MANAGER`** (new) | One unit (or several) | Runs their unit: staff, courses, fee structures within policy, approves unit expenses, sees unit finances and reports; **cannot see other units or group settings**; is the **custodian of the unit's cash drawer** and petty cash |
| `HOD` | Department in a unit | Approvals and reports for the department |
| `TEACHER` (instructors included) | Unit(s) | Own classes, attendance, grading |
| `BURSAR` | Unit(s) or group-wide | Records payments, issues invoices, prepares refunds (needs approval), cash-up |
| **`CASHIER`** (new, optional) | One unit | Records sales/payments at the front desk; no refunds, no edits to posted entries. Drawers are held by unit managers (or their named delegates); use CASHIER only if a unit wants a separate front-desk person |
| `STUDENT` | Self | Own data; derived from the `Student` record, not an assignment |

**Answer to "Admins or?":** the unit managers should be `UNIT_MANAGER`, **not** `ADMIN`. A global Admin sees every unit's money and people; a unit manager shouldn't, and an auditor shouldn't be able to change anything. If one person manages two units, give them two assignments.

### 3.2 Role assignments replace the single `User.role`
```python
class RoleAssignment(BaseModel):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="assignments")
    role = models.CharField(max_length=20, choices=Role.choices)
    unit = models.ForeignKey("org.BusinessUnit", null=True, blank=True, on_delete=models.PROTECT)
    # department FK for HOD is added in Sprint 1 when Department exists
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "role", "unit"], condition=models.Q(unit__isnull=False), name="uniq_assignment_unit"),
            models.UniqueConstraint(fields=["user", "role"], condition=models.Q(unit__isnull=True), name="uniq_assignment_global"),
            # group-wide roles must not carry a unit; unit-scoped roles must
            models.CheckConstraint(name="role_scope_valid", condition=(
                models.Q(role__in=["SUPER_ADMIN", "ADMIN", "DIRECTOR", "AUDITOR"], unit__isnull=True)
                | models.Q(role__in=["UNIT_MANAGER", "HOD", "TEACHER", "CASHIER"], unit__isnull=False)
                | models.Q(role="BURSAR")            # unit-scoped or group-wide
            )),
        ]
```
"Awaiting approval" now means **no active assignments** (and no Student link).

### 3.3 Row scoping by unit (extends `for_user`)
```python
GLOBAL_READ_ROLES = {"SUPER_ADMIN", "ADMIN", "DIRECTOR", "AUDITOR"}

class UnitScopedQuerySet(ScopedQuerySet):
    unit_field = "unit"
    def for_user(self, user):
        if user.has_global_read():               # any active assignment with a global-read role
            return self
        ids = user.unit_ids()                    # from active unit-scoped assignments
        return self.filter(**{f"{self.unit_field}__in": ids}) if ids else self.none()
```
Global **read** is not global **write**: DIRECTOR and AUDITOR are enforced read-only by permission classes, and `UNIT_MANAGER` writes are limited to objects whose `unit` is in their assignments (object-level rule). Lists accept `?unit=<id>` (validated against the caller's permitted units); omitting it means "all permitted units".

### 3.4 Authorization tests get a unit dimension
The matrix becomes **role × unit × resource × action**. Must-have cases: manager of unit A cannot read or write unit B's departments, courses, invoices, expenses or audit entries; AUDITOR can read everything finance-related and write nothing; DIRECTOR reads all dashboards, writes nothing; a user with two unit assignments sees exactly those two; a bursar with no unit assignment but a group-wide bursar assignment sees all.

---

## 4. Finance v2: from student fees to a group accounting core

**Scope:** (a) student receivables, (b) non-student revenue (Cyber sales, driving services), (c) institutional expenses, (d) cash/bank/M-Pesa accounts, (e) consolidated reporting and audit. **Not** in v2.0: payroll calculations, full tax filing, bank-feed imports, automatic M-Pesa.

### 4.1 Why double-entry, and the cost-centre rule
Single "ledger entries" (as in the blueprint) can't answer "what did each unit earn, spend and hold this month?" or support a real audit. A **journal of balanced lines** can, and it is much cheaper to design in now than to retrofit. The UI stays simple (invoice, payment, expense forms); the journal is generated underneath.

**Cost-centre rule (units are cost centres of one business):** there is **one shared chart of accounts**; **every journal line carries a `unit` (the cost centre)**; and **where money physically sits** (a unit's drawer, the shared M-Pesa agent float) is a separate **cash account**. A fee paid for a WTI invoice into the Cyber-held agent float is income and receivable for **WTI**, while the cash sits in an account **held by WCY**.

```python
class Account(BaseModel):            # one shared chart of accounts (no unit field)
    code = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=120)
    type = models.CharField(choices=[("ASSET","ASSET"),("LIABILITY","LIABILITY"),("EQUITY","EQUITY"),
                                     ("INCOME","INCOME"),("EXPENSE","EXPENSE")], max_length=10)
    parent = models.ForeignKey("self", null=True, on_delete=models.PROTECT)

class CashAccount(BaseModel):        # where money physically is (see 4A)
    account = models.OneToOneField(Account, on_delete=models.PROTECT)       # the ASSET account it maps to
    kind = models.CharField(choices=[("DRAWER","DRAWER"),("MPESA_AGENT","MPESA_AGENT"),("BANK","BANK")], max_length=12)
    name = models.CharField(max_length=80)
    custody_unit = models.ForeignKey("org.BusinessUnit", on_delete=models.PROTECT)   # e.g. WCY for the agent float
    custodian = models.ForeignKey("accounts.User", on_delete=models.PROTECT)         # named responsible person
    imprest_limit = models.DecimalField(max_digits=12, decimal_places=2, null=True)  # petty-cash float for drawers
    is_active = models.BooleanField(default=True)

class AccountingPeriod(BaseModel):   # one period for the whole business
    start = models.DateField(); end = models.DateField()
    status = models.CharField(choices=[("OPEN","OPEN"),("CLOSED","CLOSED")], default="OPEN", max_length=6)

class UnitPeriodSignoff(BaseModel):  # each unit manager signs their month
    period = models.ForeignKey(AccountingPeriod, on_delete=models.PROTECT)
    unit = models.ForeignKey("org.BusinessUnit", on_delete=models.PROTECT)
    status = models.CharField(choices=[("PENDING","PENDING"),("SIGNED","SIGNED")], default="PENDING", max_length=8)
    signed_by = models.ForeignKey("accounts.User", null=True, on_delete=models.PROTECT)
    signed_at = models.DateTimeField(null=True)

class JournalEntry(BaseModel):       # append-only (no unit here; units live on lines)
    date = models.DateField()
    memo = models.CharField(max_length=255)
    source_type = models.CharField(max_length=30)     # INVOICE | PAYMENT | EXPENSE | DISBURSEMENT | PETTY | TRANSFER | REFUND | ADJUSTMENT | DAILY_SALES ...
    source_id = models.UUIDField(null=True)
    status = models.CharField(choices=[("POSTED","POSTED"),("VOID","VOID")], default="POSTED", max_length=6)
    reverses = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)

class JournalLine(BaseModel):
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    unit = models.ForeignKey("org.BusinessUnit", on_delete=models.PROTECT)          # cost centre (required)
    cash_account = models.ForeignKey(CashAccount, null=True, on_delete=models.PROTECT)  # required when account is a cash account
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    student = models.ForeignKey("people.Student", null=True, on_delete=models.PROTECT)
    customer = models.ForeignKey("finance.Customer", null=True, on_delete=models.PROTECT)
    supplier = models.ForeignKey("finance.Supplier", null=True, on_delete=models.PROTECT)
    # CHECK: debit >= 0, credit >= 0, exactly one of them non-zero
    # Deferred constraint trigger: SUM(debit) = SUM(credit) per entry at commit
```
All of this is append-only (app checks plus DB triggers): corrections are **reversal entries** with a reason. Posting into a **CLOSED period** is rejected.

**Visibility:** `JournalLine` is unit-scoped by its own `unit`. A unit manager sees the lines of their unit(s); group roles (`SUPER_ADMIN`, `ADMIN`, `DIRECTOR`, `AUDITOR`) see all lines. An entry that touches several units (for example a WTI salary paid from the WCY-held float) shows each manager only their own lines; the auditor sees the whole entry.

### 4.2 Posting recipes
| Event | Debit | Credit |
|---|---|---|
| Student invoice (unit X) | Accounts receivable (X), student party | Tuition/course income (X) |
| Student payment (cash into a unit drawer, or M-Pesa into the agent float) | The drawer or agent-float **cash account**, line cost centre = the unit that owns the invoice | Accounts receivable (X), student party |
| Waiver or discount | Discounts/bad debt expense (X) | Accounts receivable (X) |
| Refund | Refunds/contra-income (X) | Cash / bank / M-Pesa |
| Cyber daily sales / driving services | Cash / M-Pesa | Service income (X) |
| Institutional expense (paid) | Expense category (X or HQ) | Cash / bank / M-Pesa |
| Teacher/worker paid from the agent float | Wages/fees expense, cost centre = the unit that owes it | M-Pesa agent float cash account |
| Petty cash voucher (tea, lunch, emergency) | Expense category, cost centre = the drawer's unit | That unit's drawer cash account |
| Expense on credit | Expense category | Accounts payable, supplier party |
| Supplier payment | Accounts payable | Cash / bank / M-Pesa |
| Transfer between cash accounts | Destination cash | Source cash |

Student balance = sum of receivable lines for that student. Documents (Invoice, Payment, Expense, Receipt) remain as business records; each links to its journal entry.

### 4.3 Controls an auditor will expect
- **Append-only** journal with reversal entries; mandatory reason on voids/refunds.
- **Maker-checker:** the person who records a refund, waiver or large expense cannot approve it; approval thresholds are configurable per unit.
- **Segregation:** `CASHIER` records sales but cannot refund; `BURSAR` prepares, `UNIT_MANAGER` or `ADMIN` approves.
- **Period close** per unit (monthly) and a **daily cash-up** (counted cash vs recorded sales, variance recorded and explained).
- **Audit log** on every posting, approval, close and export (who, what, when, before/after, unit).
- **Reconciliation** (v2.0: CSV import of M-Pesa/bank statements matched to payments; manual matching UI).
- **Receipts** for every expense (uploaded files, see blueprint 10.5); expenses without a receipt are flagged.
- Idempotency keys on payment and sales endpoints to prevent double posting.

### 4.4 Reporting (what "merge in revenue auditing" becomes)
- **Per unit:** income statement (income minus expenses), cash position per account, receivables ageing, collections by day/week, expenses by category, outstanding approvals.
- **Group:** the same, **consolidated** and by unit side by side; revenue by unit and by month; top expense categories; cash position across all accounts.
- **Auditor workspace:** read-only, filterable journal with drill-down from a report line to the entry to the source document and receipt; exports (CSV/PDF) are logged.
- **One business, no inter-company accounting:** there are no intercompany invoices or eliminations. Shared costs (rent, utilities, shared staff) sit in the `HQ` cost centre until an allocation job exists (later; the `unit` on every line makes it possible). The **custody and settlement views** in 4A show who physically holds what and each unit's net position.

### 4.5 What stays and what is superseded in the blueprint
- **Superseded:** the single-table `LedgerEntry` in blueprint section 6 and the finance bullets in Sprint 6.
- **Kept:** append-only principle, idempotent payments, manual M-Pesa code entry at launch (now a **reference** on the journal/payment record), receipts as `generated` files, M-Pesa automation in v2.1.

---

## 4A. Cash custody, the M-Pesa agent number, petty cash and month-end close

What you described, in system terms: **money sits in a few physical places (cash accounts), while income and costs belong to cost centres (units).** The shared M-Pesa agent float is held by WCY but receives fees for WTI, WTA and WDS and pays staff for all units. Unit managers hold cash drawers. At month end everything is reconciled.

### 4A.1 Cash accounts
| Cash account | Kind | Custody | Used for |
|---|---|---|---|
| M-Pesa agent float | `MPESA_AGENT` | WCY (named custodian) | Student fees paid by M-Pesa, staff/teacher payments, Cyber services, (possibly) public agent traffic |
| One drawer per unit | `DRAWER` | That unit's manager | Cash fee receipts, cash sales, petty cash |
| Bank (if any) | `BANK` | Group (named custodian) | Deposits, transfers |

Moves between them (drawer deposit to the float, float withdrawal to a drawer, bank transfer) are **transfer entries** with a reference and two signatures (sender and receiver).

### 4A.2 Student fee paid through the agent number
1. Staff (bursar or unit clerk) records the payment: student, invoice, amount, channel `MPESA_AGENT`, **M-Pesa transaction code (required)**, payer phone, date/time.
2. The **code must be unique across the whole business**, so the same SMS code can't be used at WTI and again at WTA.
3. Journal: debit the agent-float cash account, credit accounts receivable, **both lines with the invoice's unit as cost centre**. A receipt is issued showing the unit.
4. At month end, statement lines with no matching recorded payment go to an **"unidentified deposits"** worklist for follow-up.
Cash payments follow the same flow into the unit's drawer, with a receipt number per unit.

### 4A.3 Paying teachers and workers from the agent float
Model each payment as a **disbursement**: `payee`, `payee_phone`, `amount`, `purpose`, `unit` (cost centre), `expense_category`, `requested_by`, `approved_by`, `executed_by`, `mpesa_code`, `status` (`REQUESTED → APPROVED → EXECUTED → RECONCILED`, or `REJECTED`).
- **Requester** = the manager of the cost-centre unit. **Approver** = a different person with `ADMIN`/`SUPER_ADMIN` rights (amount thresholds configurable). **Executor** = the person operating the agent number, who **cannot approve**.
- `EXECUTED` requires the M-Pesa code; the journal posts at execution (debit expense for the unit, credit the float).
- A **payee register** (teachers, workers) with verified phone numbers; changes to a payee's number require approval (prevents wrong-number or diverted payments).
- Daily limit per payee and per float; a **daily float report** (opening, in, out, closing) for the custodian and the approver.
- Optional later: **pay runs** that batch a month's approved disbursements for teachers (a list for approval and execution; not payroll maths).

### 4A.4 Drawers and petty cash
Drawers work on an **imprest** basis: each drawer has an agreed float (`imprest_limit`).
- **Petty cash voucher:** date, amount, category (`TEA_LUNCH`, `EMERGENCY`, `TRANSPORT`, `SUPPLIES`, `OTHER`), reason, receipt (optional below a threshold, required above it), and countersignature above a limit. Journal: debit the expense for the unit, credit the drawer.
- The system **blocks a voucher that would take the drawer below zero**; emergencies still need a reason and are flagged for next-day review.
- **Daily drawer count:** expected balance (from the journal) vs counted cash; variance recorded with an explanation; repeated variances are flagged to the group admin.
- **Replenishment** is a transfer from the float or collected cash, with approval.

### 4A.5 Separate the Cyber agent business from institution money (confirm usage)
If the agent number also serves the public (normal customer deposits and withdrawals), those flows are **pass-through, not income**. Every statement line must be classified as one of: `STUDENT_FEE`, `STAFF_DISBURSEMENT`, `CYBER_SERVICE_SALE`, `PUBLIC_AGENT_TXN`, `FLOAT_TOPUP_OR_TRANSFER`, `COMMISSION`, `CHARGES`, `UNKNOWN`. Only classified lines can be marked reconciled, and **`UNKNOWN` lines block month-end close** until explained. Commission and network charges post to designated accounts (decide which cost centre gets the commission).

### 4A.6 Month-end close workflow
1. **Drawer counts** signed by each unit manager.
2. **Import the M-Pesa agent statement** (CSV or whatever export Safaricom's portal gives; the format must be confirmed from a sample).
3. **Auto-match** statement lines to recorded payments and disbursements by code, amount and time; suggest matches by payer phone.
4. **Classify and resolve** the rest (unidentified deposits, missing codes, public traffic, commission).
5. **Unit month summary** per cost centre: opening, collections by channel, expenses, petty cash, disbursements made on its behalf, closing.
6. **Unit sign-off** by each manager.
7. **Group approval and period lock** by `ADMIN`/`SUPER_ADMIN` once every unit has signed and no `UNKNOWN` lines remain; the period becomes `CLOSED`.
8. **Auditor review** (read-only) with drill-down from summary to entry to receipt; exports are logged.

### 4A.7 Two reports that fit how you actually operate
- **Custody report:** balance by cash account and custodian (physical cash and e-float), with last count date and variance.
- **Settlement position by unit (informational):** for each unit, collections attributed to it minus its attributed expenses, petty cash and staff payments made from the shared float. This shows, for example, how much of the agent float is "WTI money". There is no legal inter-company settlement; it is a management view.

### 4A.8 Who does what (segregation of duties)
| Step | Performed by | Must not be |
|---|---|---|
| Record a fee payment | Bursar / unit clerk | The approver of refunds |
| Reverse a payment, refund, waiver | Prepared by bursar | Approved by the same person |
| Request a disbursement | Manager of the cost-centre unit | The approver or executor |
| Approve a disbursement | `ADMIN` / `SUPER_ADMIN` | The requester or the executor |
| Execute (send the M-Pesa payment) | The agent-number operator in WCY | The approver; also records the code |
| Reconcile the statement | Bursar / group accountant | The executor of the same payments |
| Close the period | `ADMIN` / `SUPER_ADMIN` | Anyone before all unit sign-offs |
| Review | `AUDITOR` (read-only) | Anyone who posts entries |
These rules protect staff as much as the institution: they make every shilling traceable to a request, an approval and a code.

### 4A.9 M-Pesa automation caveat (revises blueprint opportunity 1)
The blueprint assumed M-Pesa API (Daraja) callbacks. Those APIs are generally tied to a **Paybill or Till**, not necessarily to an **agent number**. Until you confirm with Safaricom what your setup supports, plan on **statement import and matching** (section 4A.6). If automatic confirmation matters, a Paybill or Till for fee collection may be a better long-term channel.

### 4A.10 Effect on the build
No change to Sprint 0.75 beyond the confirmed codes. Sprint 6b/6c grow as shown in 6.1. The unique M-Pesa code rule, `JournalLine.unit`, `CashAccount` and the disbursement approval states are schema decisions to fix in Sprint 6a so they are never retrofitted.

---

## 5. Unit-specific notes
- **Institute and Travel Agency:** reuse the LMS modules; the differences are data (departments, courses, fee structures, certificates).
- **Driving School:** add later: instructor and vehicle resources, lesson-hour tracking against a package, test bookings, instructor/vehicle compliance records, fuel and maintenance as expenses. The fee/finance side works from day one.
- **Cyber:** customers are walk-ins (a light `Customer` record, optional), a service catalogue with prices, quick-sale entry, daily cash-up. For v2.0 use a **manual daily revenue entry** (cash and M-Pesa totals by service category) so the group audit sees Cyber from day one; real POS comes later. Avoid storing customers' documents; if a service requires it, define retention rules.
- **Compliance:** the units are cost centres of one business (confirmed), so there are no inter-company invoices. Still ask your accountant about tax invoicing rules (for example KRA's e-invoicing), the treatment of M-Pesa agent commission, and whether any unit's services are taxed differently.

---

## 6. Impact on the development process

### 6.1 Revised roadmap
| Step | Change |
|---|---|
| Sprint 0 | Done. `User.role` single field is replaced in Sprint 0.75 |
| **Sprint 0.75 (new)** | Multi-unit foundation (section 7) |
| Sprint 1 | Identity, org: add **units admin**, departments **belong to a unit**, unit switcher, audit log with unit |
| Sprint 2 to 5 | Same content, all unit-scoped (courses, enrollment, attendance, grading); registration numbers per unit |
| **Sprint 6a (new split)** | **Finance core:** chart of accounts (seeded per unit), journal engine, periods, student invoices/payments/refunds/adjustments posting to the journal, receipts, statements |
| **Sprint 6b (new)** | **Institutional finance and cash custody:** cash accounts (unit drawers, M-Pesa agent float), petty-cash vouchers, expenses and disbursements with approval, receipt uploads, transfers between cash accounts, manual daily revenue entry for Cyber/Driving, daily drawer count (section 4A) |
| **Sprint 6c (new)** | **Reporting, reconciliation and close:** M-Pesa agent statement import and classification, month-end close with unit sign-offs, per-unit and consolidated reports, custody report, auditor workspace, exports |
| Sprint 7 to 9 | Unchanged; dashboards become unit-aware |
| After launch | M-Pesa automation, Driving specifics, Cyber POS, allocation engine, payroll, tax-invoice integration |

### 6.2 Delivery phasing (recommended)
1. **Phase A (launch):** Institute + Travel Agency fully in the LMS with finance; Driving and Cyber on **finance-only** (daily revenue and expense posting), so the owner sees all four units in the consolidated audit from day one.
2. **Phase B:** Driving School features (instructors, vehicles, lesson hours).
3. **Phase C:** Cyber POS.
Reorder if Driving or Cyber is the bigger pain today.

### 6.3 Other effects
- **Finance becomes the largest module;** involve your accountant early to review the chart of accounts, posting recipes and report layouts before Sprint 6a.
- **Test load grows** (roles × units); the authorization matrix must be generated from fixtures, not hand-written.
- **UX:** a **unit switcher** in the top bar ("All units" for group roles, auto-selected for single-unit users), a unit badge on records, per-unit dashboards, and an auditor workspace.
- **Database size:** journal lines are small, but monitor growth against the free-tier cap and keep receipts in object storage.
- **Data import from v1:** every imported department, course, student enrollment and fee record needs a unit; plan a mapping sheet (for example GDS department to Travel Agency).
- **Training and change management:** managers, bursars and the auditor each need a short walkthrough; define approval thresholds with the owner before building them.

---

## 7. Sprint 0.75 — Multi-unit foundation (Copilot tasks)

Rules: follow in order; stop after each step with the check; don't add features not listed; no hard-coded colours (see palette rules in `UI_POLISH_PASS_1.md`).

### Step 1 — Decisions (you, not Copilot)
- [x] Roles in 3.1 confirmed (new: `UNIT_MANAGER`, `AUDITOR`, `CASHIER`).
- [x] Unit codes confirmed: `WTI`, `WTA`, `WDS`, `WCY` (plus `HQ`). Copy `units.md` into `docs/units.md` and confirm the official unit names in it.

### Step 2 — `apps/org`: BusinessUnit
- [ ] New app `apps/org` with `BusinessUnit(code unique, name, kind, currency="KES", modules JSONField default dict, is_active)`.
- [ ] Management command `seed_units` (idempotent) creating the units from `docs/units.md`.
- [ ] `GET /api/v1/units` returning only units the caller may see (all for group roles; assigned ones otherwise).
- [ ] Django admin registration.
**Check:** `python manage.py seed_units` twice leaves exactly the expected rows.

### Step 3 — Roles and assignments
- [ ] Update `Role` enum with the confirmed roles.
- [ ] Add `RoleAssignment` (3.2) with constraints; migration.
- [ ] Data migration: convert each existing `User.role` into an assignment (group roles with no unit; unit roles need a unit: assign manually via admin after migrating, and list those users in the migration output).
- [ ] Remove `User.role` in a second migration after code stops using it.
- [ ] `User` helpers: `roles()`, `has_role(*roles)`, `has_global_read()`, `unit_ids()` (cache per request instance).
- [ ] "Awaiting approval" = no active assignments and no linked Student.
**Check:** migrations apply on a copy of the current database; existing super admin still works.

### Step 4 — Unit scoping
- [ ] Add `UnitScopedQuerySet` (3.3) to `common/scoping.py` and a `UnitScopedViewSetMixin` that also supports `?unit=` validation against permitted units.
- [ ] Add object-level helper `can_write_unit(user, unit)`; `DIRECTOR` and `AUDITOR` never write.
**Check:** unit tests prove scoping for each role.

### Step 5 — API surface
- [ ] `GET /api/v1/me` returns `assignments: [{role, unit: {id, code, name} | null}]`, `is_global_read`, and `awaiting_approval`.
- [ ] Regenerate `openapi.yaml` and `frontend/src/api/schema.d.ts`; CI drift check stays green.

### Step 6 — Frontend
- [ ] `useMe` exposes assignments; add `useCan(roles, unitId?)` and replace direct `role` checks in `navFor` and guards with assignment-aware checks.
- [ ] `UnitProvider` + `UnitSwitcher` in the top bar: "All units" for group-wide roles; single-unit users see their unit as a badge (no dropdown). Selection stored in `localStorage`, sent as `?unit=` on list calls, and validated by the server.
- [ ] Sidebar/user card shows role label plus unit code(s).
- [ ] Departments page (from the UI polish plan) gains a required **Unit** field and a unit filter; the departments list respects the switcher.
- [ ] Dashboards: Group roles see "All units" cards; managers see their unit.

### Step 7 — Tests
- [ ] Authorization matrix over role × unit × resource × action using fixtures (units A and B, manager A, manager B, auditor, director, bursar group-wide, bursar unit A, cashier, teacher, student).
- [ ] Constraint tests: group roles cannot carry a unit; unit roles require one; duplicate assignments rejected.
- [ ] Frontend tests: `useCan`, switcher behaviour per role, nav visibility per assignment set.
**Check:** `pytest`, `ruff`, `npm run lint && npm run typecheck && npm test && npm run build` pass.

### Step 8 — Documentation
- [x] Add a "Multi-unit model" section to `README.md` and a note in the blueprint header that this addendum supersedes its role list and finance ledger.

### Definition of done
- [ ] Four units seeded; a manager of one unit cannot see another unit's data (API and UI).
- [ ] An auditor and a director can read across units and cannot write.
- [ ] `User.role` is gone; all checks use assignments.
- [ ] The Departments page is unit-aware.
- [ ] Authorization matrix covers unit boundaries.

### Prompt for Copilot (agent mode)
```
Read docs/MULTI_UNIT_AND_FINANCE_ADDENDUM.md sections 2, 3 and 7. Implement Sprint 0.75
Step 2 only (apps/org BusinessUnit, seed command, units endpoint, admin). Do not build
finance or anything else. Run the Check, show the result, and stop.
```
Repeat for Steps 3 to 8, committing after each step.

---

## 8. Open questions
**Answered:** units are cost centres of one business; unit codes `WTI`, `WTA`, `WDS`, `WCY`; new roles confirmed.

**Needed before Sprint 6a (Sprint 0.75 needs none of these):**
1. **How exactly does a student pay "by withdrawing" at the agent number?** Does the student receive cash back, or does the cash stay with the institution and only the e-float changes? (This decides how the float and drawers move.)
2. **Does the agent number also serve the public** (ordinary deposits and withdrawals), or only institutional payments? If it does, who owns the commission income?
3. Please share a **redacted sample M-Pesa agent statement** (remove names and numbers) so the importer matches the real format.
4. **Approval thresholds:** who approves disbursements and at what amounts? Daily limits for the float and per payee?
5. **Petty cash:** imprest amount per drawer, per-voucher limit, receipt-required threshold, countersign threshold, and the category list.
6. **Shared costs** (rent, utilities, shared staff): kept in `HQ`, or split across units by a rule?
7. **Who gets consolidated views:** owner only, directors? Will an external auditor need access?
8. **Financial year** and the date by which units must sign off each month.
9. Does **VAT or e-invoicing** apply to any unit, and how should **M-Pesa commission** be treated? (Ask your accountant.)
10. For launch, do Driving and Cyber need more than **daily revenue and expense posting**?
11. Is **payroll** in scope for v2.0? (Recommended: no; record teacher and staff payments as disbursements first.)
