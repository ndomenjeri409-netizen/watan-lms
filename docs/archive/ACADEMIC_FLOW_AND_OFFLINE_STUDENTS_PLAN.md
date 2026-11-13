> SUPERSEDED by MASTER_GUIDE.md; do not follow.

# Academic Flow and Offline Students: audit and Sprint 5.5 plan

Covers two questions: (1) the full course flow (unit, department, course, modules, lessons, content, assessments, teachers, timetable, attendance, grades) including editing after creation and teacher assignment; (2) students who attend in person and don't need a login. Companion to `WATAN_LMS_V2_BLUEPRINT.md` and `MULTI_UNIT_AND_FINANCE_ADDENDUM.md`.

## 0. Status in one page

**Was it planned?** Partly.
- The blueprint scheduled the pieces: Sprint 2 (courses, modules, lessons, materials, course editor, archive), Sprint 3 (students, enrollment), Sprint 4 (classes, timetable, attendance), Sprint 5 (assessments, grades).
- **My plan under-specified two things:** how a teacher is assigned to teach (the blueprint listed `assignedTeacherIds` on a course and `ClassGroup` under scheduling but never defined the link between them), and the post-creation lifecycle of a course (edit, reorder, publish, unpublish, duplicate, archive, restrictions once students are enrolled). So the sprints can be "done" while this flow still feels broken. That is a plan gap, not a schedule you missed.
- **Fix:** an audit now (section 7) to see what exists, then a short **Sprint 5.5** (section 8) to close the gaps, placed **after Section A step A4** (which changes the unit fields on Course, Program, Enrollment and TimetableSlot) and **before A6 and 6b**, so the authorization matrix covers the new endpoints.

**Offline students:** the architecture supports them because a `Student` record is separate from a login. Whether your code really allows a student with **no account** across registration, fees, attendance and grades needs the audit. Section 6 states the requirements.

---

## 1. The academic model: curriculum vs class

The key idea: **a Course is the curriculum; a Class (your `ClassGroup`) is one delivery of that course.** Everything that changes per intake hangs off the Class.

```
BusinessUnit
 └─ Department
     └─ Program (optional grouping)
         └─ Course  ........................ curriculum (what is taught)
             ├─ Module (section)
             │   └─ Lesson
             │       └─ LessonItem: video link | file | text | link   (content)
             └─ Assessment template? (see below)

Course + AcademicPeriod (term/intake) + cohort name
 └─ Class (delivery)  ....................... who, when, where
     ├─ ClassTeacher (teacher + role LEAD/ASSISTANT)
     ├─ TimetableSlot (day, time, room, teacher) ── AttendanceSession (one per occurrence)
     ├─ Enrollment (student in this class)
     └─ Assessment instances (due dates) ── Submission ── Grade (per enrollment)
```

**Why separate them:** the same course runs for many intakes; teachers, rooms, dates, attendance, grades and fees differ per intake. Editing curriculum must not rewrite history, and one teacher's change must not affect other classes.

**Assessments:** content-level definition (what the task is) lives on the Course or Module; each Class gets its own instance with dates and weighting (or you can attach assessments directly to the Class; decide in D4).

**Everything carries the unit.** Course, Class, Enrollment, TimetableSlot and Assessment all have a direct `unit` that must equal the parent's unit (Section A, step A4).

## 2. Who can do what (teacher assignment)

Two separate ideas, because "who teaches" and "who may edit the curriculum" differ:

| Concept | Table | Meaning |
|---|---|---|
| **Teaching assignment** | `ClassTeacher(class, teacher, role[LEAD|ASSISTANT], is_active)` | This teacher delivers this class: sees the roster, takes attendance, enters grades, posts class announcements |
| **Course authorship** | `CourseAssignment(course, teacher, can_edit_content)` | This teacher may edit lessons/materials of this course (curriculum), or only view it |

Rules:
- A teacher assigned to a class can **view** the course content, **mark attendance** and **grade** for that class only.
- A teacher may **edit** content only when `can_edit_content` is true for the course.
- `HOD` (their department) and `UNIT_MANAGER` (their unit) manage both assignment tables, create courses and classes, and publish.
- `ADMIN`/`SUPER_ADMIN` can do everything; `DIRECTOR`/`AUDITOR` read only.
- A teacher can be assigned across several units (separate role assignments per unit); the unit scope still applies.
- Clash checks on timetable slots: same teacher, same room, same class at the same time are rejected.

## 3. Lifecycles and edit rules

**Course:** `DRAFT → PUBLISHED → ARCHIVED` (optionally `IN_REVIEW` before publish).
- Editable any time by authorised users with an audit entry; use an `updated_at`/`version` check (optimistic locking) so two editors can't overwrite each other silently.
- **Once a course has classes or enrollments:** you may edit titles, descriptions, content and order. You may **not** delete modules/lessons/assessments that have submissions, grades or attendance linked; **archive** them instead (hidden from new classes, kept for history). You may not change the course's unit or department.
- **Duplicate course** (copies curriculum into a new draft, optionally into another department of the same unit) to start a new version without disturbing running classes.
- Archive/unarchive; archived courses can't get new classes.

**Class:** `PLANNED → OPEN → RUNNING → COMPLETED` (or `CANCELLED`).
- Creating a class requires: course (must be PUBLISHED), academic period/intake, name/cohort, capacity, unit (derived), at least one teacher before `RUNNING`.
- Closing a class locks attendance and grade entry after the HOD approves final grades.

**Lesson content items:** `video` (external link such as unlisted YouTube), `file` (uploaded via the `files` app), `text`, `link`; ordered; visible/hidden toggle; per-item audit.

**Assessment:** `DRAFT → PUBLISHED → CLOSED`. **Grade:** `DRAFT → SUBMITTED → APPROVED → PUBLISHED` (existing workflow).

## 4. Screens needed (by role)

| Role | Screens |
|---|---|
| **HOD / Unit manager** | Courses list; **Course editor** (details tab, **curriculum tree** with add/edit/delete/reorder of modules, lessons and items, **Teachers tab**, Classes tab, Settings: publish / unpublish / duplicate / archive); **Classes** (create from course + period, set capacity, assign teachers, build timetable, view roster, close class); Enrollment queue; Teacher workload view |
| **Teacher** | **My classes** list; **Class page** with tabs: Roster, Timetable, Attendance, Assessments, Gradebook, Materials; **My courses** (content editor only where `can_edit_content`) |
| **Student (if they have an account)** | My classes, timetable, materials, grades |
| **Staff for students without accounts** | Everything above is operated by the teacher/front desk on their behalf (section 6) |

Course editing is a standard "edit page" with sections, not a one-time creation form. Use the list-page recipe and Drawer for small forms, and a dedicated page for the curriculum tree.

## 5. How the pieces relate (what must be true in the data)

- `Enrollment` references the **Class** (and through it the course, period and unit); it is also the anchor for invoices, attendance records and grades.
- `TimetableSlot` references Class, teacher, room (and unit); it generates **AttendanceSession** occurrences for dates in the period.
- `AttendanceRecord` is one row per student per session; marked by a teacher, by QR self check-in (only if the student has an account or card), or by roster import.
- `Assessment` instance references Class; `Submission` and `Grade` reference the **Enrollment**.
- Deleting is replaced by archiving anywhere history exists.

## 6. Students without a login (offline learners)

**Principle:** a student is a **record**, not an account. The login is optional and can be added later.

### 6.1 Model requirements
`Student` (group-level person; enrollments are per unit and class):
- Identity: full name; registration number (per unit, per decision D1); date of birth (optional); gender (optional); national ID or birth certificate number (optional, only if needed); photo (optional, files app).
- Contact: **phone (required, primary contact)**, email (optional), county/area, guardian or sponsor name and phone (optional, strongly recommended for minors), emergency contact.
- Status: `APPLICANT → ACTIVE → COMPLETED | WITHDRAWN | SUSPENDED | DEFERRED`, with dates and reasons.
- Account: `user` FK **nullable**; `account_status` = `NONE | INVITED | ACTIVE`.
- Duplicate protection: warn on same phone, same name and date of birth, or same national ID; staff must confirm to proceed; merging duplicates is an admin action with an audit trail.

### 6.2 Flows that must work with no account
| Need | How it works without a login |
|---|---|
| **Registration** | Front-desk form with minimal required fields (name, phone, unit, course/class); a student can be created in under a minute. Bulk import from CSV/Excel for existing rosters with a validation report |
| **Enrollment and fees** | Staff enrol the student in a class; the invoice is generated from the fee structure; the Bursar records payments (cash or M-Pesa code); receipts and statements are PDFs staff can print or send |
| **Attendance** | Teacher marks attendance from the roster on their phone (present/absent/late/excused). No student device needed |
| **Grades** | Teacher enters marks; HOD approves; staff print the report card/transcript |
| **Communication** | By phone (SMS or WhatsApp later), announcements printed or read in class |
| **Certificates** | Generated and printed by staff, with a QR code for public verification |
| **Optional portal access** | Staff press "Invite to portal" when the student has an email; the existing server-side invite flow creates the account and links it to the Student. Students claim access only through staff-initiated invites in v2.0 |

### 6.3 Nice-to-have (after launch)
- **Printed student card with a QR code**: the teacher scans it with their phone to mark attendance, so offline students are still tracked quickly.
- SMS reminders for fees and class changes (cost per SMS applies).
- Self-service portal claim using registration number plus phone verification.

### 6.4 Data protection
Collect only the fields you use; restrict who can view national ID numbers and photos; keep access logs; define retention (for example, what happens to records of students who withdrew). Have the policy reviewed against Kenya's Data Protection Act (2019).

---

## 7. Audit first (Copilot reports; no code changes)

Prompt:
```
Read docs/ACADEMIC_FLOW_AND_OFFLINE_STUDENTS_PLAN.md sections 1 to 6. Audit the repository and
produce ONE table: item | status (done / partial / missing) | evidence (file, endpoint,
test or screen). Do not change code. Stop after the table.
```
Items to audit:
1. Course API and UI: create, **edit after creation**, publish, unpublish, archive, **duplicate**.
2. Curriculum tree: add, edit, delete/archive, **reorder** modules, lessons and items.
3. Lesson items: video link, file upload (files app), text, link; visibility toggle.
4. **Teacher assignment:** is there a model/endpoint/UI for course authorship and for class teaching? Where is `assignedTeacherIds` or equivalent used?
5. Class: model fields (course, period, cohort, capacity, status, unit); creation UI; lifecycle transitions.
6. TimetableSlot: links to class, teacher, room, unit; clash detection; generation of attendance sessions.
7. Attendance: marking by teacher from the roster; one record per student per session (unique constraint); QR check-in; behaviour for students without accounts.
8. Assessments: link to course or class; submissions; grades keyed to the enrollment; approval workflow.
9. Enrollment: references the class; unit consistency checks.
10. Edit-lock rules: can a module/lesson with grades or attendance be deleted today?
11. Optimistic locking or "edited by someone else" protection on course editing.
12. **Student without account:** is `Student.user` nullable? Can staff create and enrol a student with no Firebase account? Do invoices, payments, receipts, statements, attendance and grades all work for such a student from staff screens?
13. Student registration form (minimal fields), CSV import, duplicate warning, phone required.
14. Role/unit authorization tests covering these resources.

---

## 8. Sprint 5.5: close the gaps (after the audit; implement only what is missing)

Place: after Section A step A4, before A6 and 6b. Work one step at a time; stop after each with the check result and update `docs/PROGRESS.md`.

### Decisions to confirm first
- **D4 — CONFIRMED:** support both fixed terms and rolling intakes; assessments are course templates instantiated per class.
- **D5 — CONFIRMED:** use both class-teaching and course-author assignments.
- **D6 — CONFIRMED:** require name, phone, unit, and class at student registration; other fields are optional.
- **D7 — CONFIRMED:** warn on matching phone, name plus date of birth, or national ID.
- **D8 — CONFIRMED:** portal accounts are created only through staff-initiated invitations.

### Step 1: Teacher assignment
- [x] Models: `ClassTeacher`, `CourseAssignment` (unit derived from the course/class; unique per teacher and target), with backfills for legacy class leads and eligible course authors.
- [x] API: assign/unassign; teachers see only their assigned classes and active course assignments; HOD, unit manager, and admin manage assignments.
- [x] UI: course-teacher management, unit-filtered class teacher picker, and teacher workload counts.
- [x] Permissions: class-level attendance and grading; course-level content edits; unit-scoped teacher eligibility and focused tests.
- **Check — PASS (2026-11-07):** full backend SQLite suite 120 passed, 6 PostgreSQL-only skipped; frontend 72 passed; lint, typecheck, production build, migration drift and OpenAPI checks passed. No configured Neon database was used.

### Step 2: Course lifecycle and editor
- [ ] Edit page with tabs (Details, Curriculum, Teachers, Classes, Settings).
- [ ] Publish, unpublish, archive/unarchive, **duplicate**.
- [ ] Locked fields (unit, department) once classes exist; archive instead of delete when history exists.
- [ ] Optimistic locking (`version` or `updated_at` check) with a clear "someone else edited this" message.
- [ ] Audit entries with unit for every change.
- **Check:** edit, reorder and archive work; deletion of graded or attended content is refused with a helpful message; two concurrent edits don't overwrite each other.

### Step 3: Curriculum tree
- [ ] Add/edit/archive modules, lessons and items; **drag-and-drop or up/down reorder** with a stored `position`.
- [ ] Item types: video link (validated allow-list of hosts), file (files app), text, link; show/hide.
- [ ] Bulk "collapse/expand" and a preview-as-student mode.
- **Check:** reordering persists; hidden items don't appear to students; uploads respect the files policy.

### Step 4: Class creation and linkage
- [ ] Create class from a published course + period + cohort + capacity; lifecycle transitions with rules.
- [ ] Ensure Enrollment, TimetableSlot, AttendanceSession, Assessment instances and Grades all reference the class/enrollment chain in section 5; add missing FKs and consistency checks.
- [ ] Timetable clash checks (teacher, room, class).
- **Check:** end-to-end path works: create course, publish, create class, assign teacher, build timetable, enrol student, mark attendance, grade, approve.

### Step 5: Students without accounts
- [ ] Make `Student.user` nullable if it isn't; add `account_status`.
- [ ] Quick registration form (minimal fields), duplicate warning, CSV import with validation report.
- [ ] Verify and fix staff-side flows for no-account students: invoices, payments, receipts, statements, roster attendance, grade entry, report card/transcript PDF.
- [ ] "Invite to portal" action for students with an email (reuse the server-side provisioning).
- [ ] Student list shows an account badge (No account / Invited / Active).
- **Check:** a student with no account can be registered, enrolled, invoiced, paid, marked present, graded and given a printable statement without ever logging in.

### Step 6: Tests and docs
- [ ] Role × unit matrix entries for every new endpoint (feeds A6); concurrency test for course edits; clash tests; no-account student journey test.
- [ ] Update `docs/PROGRESS.md` and add a short "Academic flow" section to the README.

### Definition of done
- [ ] A HOD can create, edit, reorder, publish, duplicate and archive courses, and assign teachers.
- [ ] A class can be created from a published course, with teachers, timetable and enrolled students.
- [ ] A teacher can run attendance and grading for their classes only.
- [ ] A student with no account is fully usable for accounting and management.
- [ ] Authorization tests cover all new endpoints.

## Where this fits in the overall order
`B.2 finish → A2 → A3 → A4 and A5 (after D2 and D1) → Sprint 5.5 → A6 → B.3 to B.6 → 6b and onward`
Defer to after launch: course versioning and snapshots, student card QR scanning, SMS reminders, self-service portal claim, driving lesson hours and vehicle scheduling.
