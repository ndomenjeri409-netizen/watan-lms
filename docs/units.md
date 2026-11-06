# Business units (seed data for `seed_units`)

Copy this file to `docs/units.md`. The `seed_units` command reads these rows. Confirm the official names before seeding.

| Code | Name | Kind | Currency | Modules | Notes |
|---|---|---|---|---|---|
| WTI | Watan Training Institute | ACADEMIC | KES | lms, attendance, gradebook, timetable, finance | Regular courses in departments (ICT, Business & Finance Studies, Languages, Travel & Tourism, ...) |
| WTA | Watan Travel Agency | TRAINING | KES | lms, attendance, certificates, finance | GDS training: Amadeus Level 1/2, Travelport Level 1/2. Existing department "IATA Global Distribution Systems (GDS)" belongs here |
| WDS | Watan Driving School | DRIVING | KES | lms, attendance, finance | NTSA driving courses and related services; instructor/vehicle scheduling comes later |
| WCY | Watan Cyber | SERVICES | KES | finance | Cyber services; holds the institution's M-Pesa agent number (custodian of the shared float) |
| HQ | Group / Shared | GROUP | KES | finance | Cost centre for shared costs; not a customer-facing unit |

Rules:
- All four units are **cost centres of one business** (not separate legal entities).
- `kind` for HQ is `GROUP` (add it to the `BusinessUnit.Kind` choices; it is excluded from course/enrolment screens).
- Codes are permanent identifiers: do not rename them after data exists.
