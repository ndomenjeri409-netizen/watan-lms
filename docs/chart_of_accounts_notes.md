# Chart of Accounts: draft notes for your accountant

**Status: DRAFT. Not approved. Do not load into production.** `chart_of_accounts_DRAFT.csv` is a starting point for your accountant to edit. After approval, rename it to `docs/chart_of_accounts.csv`; only that name is loaded by the `seed_chart` command. This draft is not tax or accounting advice.

## Structure
- **92 rows:** 71 postable accounts and 21 header (group) accounts used only for report totals. Postings to header accounts are rejected.
- **One shared chart for the whole business.** The four units (WTI, WTA, WDS, WCY, plus HQ for shared items) are a **cost-centre dimension on every journal line**, not separate accounts. So there is one "Tuition and course fees" account; WTI's tuition and WTA's GDS fees are told apart by the unit on the line.
- **Codes:** 1xxx assets, 2xxx liabilities, 3xxx equity, 4xxx income, 5xxx direct costs, 6xxx operating expenses.
- **Cash accounts** (`is_cash = true`) map one-to-one to the cash locations in the system: a drawer per unit (1110 to 1113), the M-Pesa agent float held by WCY (1120), and the bank (1130, remove if there is no bank account).
- **Normal balances:** assets and expenses are debit-normal; liabilities, equity and income are credit-normal. Contra accounts (4910, 4920, 1590) carry the opposite balance.

## Columns
`code, name, type, parent, is_cash, is_postable`
`type` is one of ASSET, LIABILITY, EQUITY, INCOME, EXPENSE. `parent` is a parent code (blank for top level). A parent must be a header and share the child's type.

## Items to check with the accountant
1. Is there a **bank account**? If not, delete 1130.
2. Are NTSA, IATA or examination-body fees ever **collected on behalf of a third party**? If yes they belong in 2270 (pass-through), not income.
3. Are **waivers and scholarships** best shown as contra-income (4910, as drafted) or as an expense? Posting recipes in the addendum say "discounts/bad debt expense"; align the wording once decided.
4. **Depreciation** (1590, 6510): keep, or handle outside the system?
5. **Payroll and statutory deductions** (2310, 6140): the system records staff and teacher payments as disbursements, not payroll. Keep 2310 and 6140 only if you want them ready.
6. **Tax** (2320): is any unit VAT-registered or subject to other taxes that need separate tracking?
7. **M-Pesa agent commission** (4310): which cost centre should receive it, WCY or HQ?
8. **Unidentified receipts** (2250): a suspense liability for M-Pesa deposits not yet matched to a student. Agree how long items may stay there before follow-up.
9. **Cash over and short** (6920) and **reconciliation differences** (6930): approve who may write off differences and up to what amount.
10. Do any units need extra income or expense lines (for example specific driving or GDS costs)? Add rows rather than reusing "Other".

## How the system uses these accounts
| Event | Debit | Credit |
|---|---|---|
| Student invoice | 1210 Student fees receivable | 4110 Tuition and course fees (or 4120 to 4160 by fee type) |
| Fee paid by M-Pesa to the agent number | 1120 M-Pesa agent float | 1210 (or 2250 if the payer is not yet identified) |
| Fee paid in cash | The unit's drawer (1110 to 1113) | 1210 |
| Fee paid in advance | Cash account | 2200 Student advance payments |
| Waiver or scholarship | 4910 | 1210 |
| Refund | 4920 (or 2210 when approved but unpaid) | Cash account |
| Teacher paid from the float | 5110 | 1120 |
| Staff wages paid from the float | 6110 | 1120 |
| Petty cash voucher | Expense account per the map below | The unit's drawer |
| Drawer variance (short) / (over) | 6920 / the drawer | the drawer / 6920 |
| Cyber service sale (cash or M-Pesa) | Drawer or 1120 | 4210 to 4240 |
| Public agent deposit or withdrawal | Transfer between the drawer and 1120 (no income) | |
| M-Pesa commission received | 1120 | 4310 |
| M-Pesa charges paid | 6380 | 1120 |
| Expense on credit, then supplier payment | Expense account, then 2110 | 2110, then cash account |
| Approved reconciliation write-off | 6930 | 1120 or the drawer |

## Petty cash category map (proposed)
| Voucher category | Account |
|---|---|
| TEA_LUNCH | 6130 Staff welfare (tea, lunch, refreshments) |
| EMERGENCY | 6390 Emergency and miscellaneous expenses |
| TRANSPORT | 6340 Transport and travel |
| SUPPLIES | 6330 Stationery and printing (administration) |
| OTHER | 6390 Emergency and miscellaneous expenses |

## Statement classification map (proposed, used in reconciliation)
| Class | Posting |
|---|---|
| STUDENT_FEE | As "fee paid by M-Pesa" above |
| STAFF_DISBURSEMENT | Matched to an executed disbursement |
| CYBER_SERVICE_SALE | 4210 to 4240 |
| PUBLIC_AGENT_TXN | Transfer between drawer and float; no income |
| FLOAT_TOPUP_OR_TRANSFER | Transfer between cash accounts |
| COMMISSION | 4310 |
| CHARGES | 6380 |
| UNKNOWN | 2250 until explained; blocks month-end close |

## Instructions for Copilot (after the accountant approves)
1. Add `is_postable` (boolean, default true) to `Account`; the posting service rejects lines to accounts where it is false.
2. Implement `seed_chart` to load `docs/chart_of_accounts.csv` idempotently (upsert by `code`; parents resolved by code; never delete accounts that already have postings).
3. Create `CashAccount` rows for 1110 to 1113, 1120 and 1130 with named custodians (`custody_unit` WCY for 1120). Custodians and opening balances come from an approved list; do not invent them.
4. Load the petty-cash and statement-class maps from `docs/` configuration, not from code constants.
5. Add a test that every posting recipe's accounts exist, parents share types, and no posting targets a header account.
