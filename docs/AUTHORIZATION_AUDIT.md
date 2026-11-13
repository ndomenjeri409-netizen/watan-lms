# Authorization Consolidation — AC1 Baseline Audit

**Date:** 2026-11-08

**Scope:** Backend custom DRF permission classes, concrete `for_user` querysets (including inherited unit scoping), and API views that inspect `user.role` or `role_scopes`. This began as the AC1 baseline audit and is updated as AC3 apps are migrated.

## Role model

`Role` defines SUPER_ADMIN, ADMIN, DIRECTOR, AUDITOR, UNIT_MANAGER, HOD, TEACHER, BURSAR, CASHIER and STUDENT. `User.role` collapses active assignments to one primary role, in this order: SUPER_ADMIN > ADMIN > DIRECTOR > AUDITOR > UNIT_MANAGER > HOD > BURSAR > TEACHER > CASHIER > STUDENT. Branches using `user.role` therefore ignore other assignments. `has_role()` checks memberships and is the multi-role-safe alternative, but it does not by itself establish the correct unit scope.

## Permission classes

| Class (source) | Current role gate | Material omissions / multi-role behavior |
|---|---|---|
| `OrgManagementPermission` (`common/permissions.py`) | Safe: SUPER_ADMIN, ADMIN, DIRECTOR, AUDITOR, UNIT_MANAGER, HOD. Writes: SUPER_ADMIN, ADMIN. | BURSAR, CASHIER, TEACHER and STUDENT cannot read org endpoints; UNIT_MANAGER/HOD cannot write despite unit/department roles. Uses primary role. |
| `UserManagementPermission` (`common/permissions.py`) | Ordinary reads: SUPER_ADMIN, ADMIN, DIRECTOR, HOD, UNIT_MANAGER. `invite`/`role`: SUPER_ADMIN, ADMIN only. | AUDITOR, BURSAR, CASHIER, TEACHER and STUDENT are omitted. Object role changes also compare only primary roles. |
| `PeopleManagementPermission` (`apps/people/permissions.py`) | Safe: global readers; UNIT_MANAGER/HOD for staff; UNIT_MANAGER/HOD/STUDENT for guardians; UNIT_MANAGER/HOD/TEACHER/STUDENT for students. Writes: SUPER_ADMIN/ADMIN; scoped UNIT_MANAGER/HOD/STUDENT guardian changes. | Directors/auditors are read-only; guardian writes and student visibility are scoped to assigned units/departments or self. |
| `ApplicationPermission` (`apps/enrollment/permissions.py`) | Public `create` is overridden with `AllowAny`; `approve`/`reject`: SUPER_ADMIN, ADMIN, HOD, UNIT_MANAGER. Safe requests: global readers, HOD, UNIT_MANAGER. | HOD is limited to assigned departments and UNIT_MANAGER to assigned units. AUDITOR and DIRECTOR are read-only; scope checks use role membership. |
| `EnrollmentPermission` (`apps/enrollment/permissions.py`) | Safe reads: global readers, HOD, UNIT_MANAGER, TEACHER, STUDENT. `transition`: SUPER_ADMIN, ADMIN, HOD, UNIT_MANAGER, STUDENT. | HOD and UNIT_MANAGER are scoped to their departments/units; teachers require active content-edit assignments; students see and may cancel only their own enrollments. AUDITOR and DIRECTOR are read-only. |
| `SchedulingPermission` / `ClassTeacherPermission` (`apps/scheduling/permissions.py`) | Safe: global readers, UNIT_MANAGER, HOD, TEACHER, STUDENT. Writes: SUPER_ADMIN, ADMIN, HOD, UNIT_MANAGER; TEACHER is added only for class/timetable management. | BURSAR/CASHIER omitted. Directors/auditors are read-only. HOD and unit-manager writes are department/unit scoped; teacher writes require the assigned course or class. |
| `AttendancePermission` (`apps/attendance/permissions.py`) | Check-in: STUDENT only. Open/QR/close: SUPER_ADMIN, ADMIN, HOD, UNIT_MANAGER, TEACHER. Safe reads: global readers, HOD, UNIT_MANAGER, TEACHER, STUDENT. | Directors/auditors are read-only; unit-manager and HOD actions are scoped; role membership supports combined assignments. BURSAR/CASHIER have no attendance access. |
| `AcademicsPermission` (`apps/academics/permissions.py`) | Safe requests pass this gate; writes: SUPER_ADMIN, ADMIN, HOD, UNIT_MANAGER, TEACHER (teacher create only on flagged views). Course list/retrieve is separately public. | DIRECTOR, AUDITOR, BURSAR, CASHIER and STUDENT cannot write. Safe access depends on view queryset scoping. `may_manage_course` uses primary role. |
| `CourseAssignmentPermission` (`apps/academics/permissions.py`) | Safe: SUPER_ADMIN, ADMIN, DIRECTOR, AUDITOR, HOD, UNIT_MANAGER, TEACHER. Writes: SUPER_ADMIN, ADMIN, HOD, UNIT_MANAGER. | TEACHER cannot create/change assignments; BURSAR, CASHIER and STUDENT omitted. Object checks use primary-role `may_manage_course`. |
| `AssessmentPermission` (`apps/assessment/permissions.py`) | Submission create: STUDENT. Grade create/update: SUPER_ADMIN, ADMIN, TEACHER. Assessment create/default writes: SUPER_ADMIN, ADMIN, HOD, TEACHER. Submit-for-approval: SUPER_ADMIN, ADMIN, TEACHER. Approve/reject: SUPER_ADMIN, ADMIN, HOD. Safe: SUPER_ADMIN, ADMIN, DIRECTOR, HOD, TEACHER, STUDENT. | UNIT_MANAGER is omitted from assessment management; AUDITOR, BURSAR and CASHIER are omitted from reads/writes. Primary-role checks can hide a valid secondary assignment. |
| `GradebookPermission` (`apps/assessment/permissions.py`) | SUPER_ADMIN, ADMIN, DIRECTOR, HOD, TEACHER, STUDENT. | AUDITOR, UNIT_MANAGER, BURSAR and CASHIER omitted. Subsequent row checks also use primary role. |
| `FinancePermission` (`apps/finance/permissions.py`) | Read: global roles (SUPER_ADMIN, ADMIN, DIRECTOR, AUDITOR), BURSAR, UNIT_MANAGER, CASHIER; STUDENT only on flagged read-only views. Writes: SUPER_ADMIN, ADMIN, BURSAR, UNIT_MANAGER; payment create also allows CASHIER; approve/reverse/void allows SUPER_ADMIN, ADMIN, UNIT_MANAGER. | TEACHER omitted; STUDENT write omitted; CASHIER cannot write except payment creation. Uses `has_role()` and unit checks, so role membership is not collapsed to `user.role`. |
| `CMSPermission` (`apps/cms/permissions.py`) | Safe requests are public; writes require SUPER_ADMIN or ADMIN. | DIRECTOR, AUDITOR, UNIT_MANAGER, HOD, TEACHER, BURSAR, CASHIER and STUDENT cannot write. |

Built-in `IsAuthenticated` and `AllowAny` are also used on individual views; they do not replace the row/object checks described below.

## `for_user` queryset inventory

| Queryset(s) | Current visibility and omitted roles |
|---|---|
| `ScopedQuerySet` (`common/scoping.py`) | Abstract contract only; raises `NotImplementedError`. |
| `UnitScopedQuerySet` (`common/scoping.py`) | Anonymous users see none. SUPER_ADMIN, ADMIN, DIRECTOR, AUDITOR and group-assigned BURSAR see all rows. Other users see rows whose `unit_field` is in their combined `unit_ids()`; it does not distinguish the role attached to each unit. |
| `UserQuerySet` (`apps/accounts/models.py`) | SUPER_ADMIN/ADMIN/DIRECTOR see all; HOD sees users in scoped departments plus self; UNIT_MANAGER sees users assigned to its units; all other roles, including AUDITOR and BURSAR, see only self. Membership checks are used, but the first matching branch wins for multi-role users. |
| `StudentQuerySet` (`apps/people/models.py`) | Global readers all; UNIT_MANAGER assigned units; HOD assigned departments; TEACHER students with active course access through assigned classes; STUDENT self. Scopes are unioned across roles; other roles get none. |
| `StaffProfileQuerySet` (`apps/people/models.py`) | Global readers all; UNIT_MANAGER assigned units; HOD assigned departments. Other roles get none. |
| `GuardianQuerySet` (`apps/people/models.py`) | Global readers all; UNIT_MANAGER assigned units; HOD assigned departments; STUDENT own guardians. Scopes are unioned across roles; other roles get none. |
| `ApplicationQuerySet` (`apps/enrollment/models.py`) | Global readers all; HOD assigned departments; UNIT_MANAGER assigned units. Other roles get none. Scopes are unioned for multi-role users. |
| `EnrollmentQuerySet` (`apps/enrollment/models.py`) | Global readers all; HOD assigned departments; UNIT_MANAGER assigned units; TEACHER courses with active content-edit assignments; STUDENT own rows. Scopes are unioned for multi-role users; other roles get none. |
| `CourseAccessQuerySet` (`apps/enrollment/models.py`) | Global readers all; HOD assigned departments; UNIT_MANAGER assigned units; TEACHER active access for active content-edit assignments; STUDENT own active access. Scopes are unioned for multi-role users; other roles get none. |
| `CampusQuerySet` (`apps/org/models.py`) | SUPER_ADMIN/ADMIN/DIRECTOR all; HOD departments. UNIT_MANAGER and other non-listed roles get none. |
| `DepartmentQuerySet` (`apps/org/models.py`) | Inherits unit scope; global-read/group BURSAR sees all, HOD is narrowed to `RoleScope`, and any other role with unit assignments sees departments in those units. A user with both HOD and UNIT_MANAGER is narrowed to HOD departments. |
| `ProgramQuerySet` (`apps/org/models.py`) | Inherits unit scope; HOD narrowed to visible departments; other assigned-unit roles see all programs in their units. Global-read/group BURSAR sees all. |
| `AcademicPeriodQuerySet` (`apps/org/models.py`) | SUPER_ADMIN/ADMIN/DIRECTOR/HOD see all. AUDITOR, UNIT_MANAGER, BURSAR, CASHIER, TEACHER and STUDENT get none. Uses primary role. |
| `CourseQuerySet` (`apps/academics/models.py`) | Anonymous users see published active courses. Global-read/group BURSAR sees all; STUDENT sees published active courses in own department; HOD scoped departments; UNIT_MANAGER assigned units; TEACHER assigned courses plus published active courses in assigned units; other unit roles see published active courses in their units. |
| `CourseAssignmentQuerySet` (`apps/academics/models.py`) | Inherits unit scope; global-read/group BURSAR sees all; UNIT_MANAGER sees assignments in its units; TEACHER sees own active assignments; HOD sees scoped departments. Other unit roles fall through to all assignments in their units. |
| `CourseChildQuerySet`, `UnitQuerySet`, `LessonQuerySet`, `MaterialQuerySet` (`apps/academics/models.py`) | Visibility follows the parent `CourseQuerySet`; only SUPER_ADMIN/ADMIN/DIRECTOR/HOD/TEACHER can also see inactive children. UNIT_MANAGER, AUDITOR, BURSAR, CASHIER and STUDENT are limited to active children. `CourseModule` uses `CourseChildQuerySet`. |
| `RoomQuerySet` (`apps/scheduling/models.py`) | Global readers all; HOD assigned departments; UNIT_MANAGER and TEACHER assigned units; STUDENT rooms on scheduled classes available through active course access. Role scopes are unioned. |
| `ClassGroupQuerySet` (`apps/scheduling/models.py`) | Global readers all; HOD assigned departments; UNIT_MANAGER assigned units; TEACHER lead/active-assistant classes; STUDENT active classes from active course access. Role scopes are unioned. |
| `ClassTeacherQuerySet` (`apps/scheduling/models.py`) | Global readers all; UNIT_MANAGER assignments in assigned units; HOD assignments in scoped departments; TEACHER own active assignments. Role scopes are unioned; other roles get none. |
| `TimetableSlotQuerySet` (`apps/scheduling/models.py`) | Slots whose class groups are visible through `ClassGroupQuerySet`, including students without unit assignments and global auditors. |
| `AttendanceSessionQuerySet` (`apps/attendance/models.py`) | Global readers all; HOD assigned departments; UNIT_MANAGER assigned units; TEACHER assigned classes; STUDENT open sessions for active course access. Scopes are unioned across roles; other roles get none. |
| `AttendanceRecordQuerySet` (`apps/attendance/models.py`) | Global readers all; HOD assigned departments; UNIT_MANAGER assigned units; TEACHER assigned classes; STUDENT own records. Scopes are unioned across roles; other roles get none. |
| `AssessmentQuerySet` (`apps/assessment/models.py`) | SUPER_ADMIN/ADMIN/DIRECTOR all; HOD scoped departments; TEACHER assigned classes/content-edit courses; STUDENT published assessments for accessible courses. UNIT_MANAGER, AUDITOR, BURSAR and CASHIER get none. |
| `SubmissionQuerySet` (`apps/assessment/models.py`) | Same admin/HOD/teacher scoping; STUDENT sees own submissions. UNIT_MANAGER, AUDITOR, BURSAR and CASHIER get none. |
| `GradeQuerySet` (`apps/assessment/models.py`) | Same admin/HOD/teacher scoping; STUDENT sees own published grades. UNIT_MANAGER, AUDITOR, BURSAR and CASHIER get none. |
| `FeeStructureQuerySet`, `JournalLineQuerySet` (`apps/finance/models.py`) | Inherit `UnitScopedQuerySet`: global-read/group BURSAR sees all; any assigned-unit role sees rows in its assigned units; STUDENT without a unit sees none. |
| `InvoiceQuerySet` (`apps/finance/models.py`) | Global-read/group BURSAR all; STUDENT own invoices; otherwise all invoices in `unit_ids()`. |
| `JournalEntryQuerySet` (`apps/finance/models.py`) | Global-read/group BURSAR all; otherwise journal entries with lines in any assigned unit; roles without unit assignments see none. |
| `AuditLogQuerySet` (`apps/audit/models.py`) | SUPER_ADMIN/ADMIN/DIRECTOR/AUDITOR all; UNIT_MANAGER only unit-scope logs for assigned units. HOD, BURSAR, TEACHER, CASHIER and STUDENT get none. |
| `PublishedContentQuerySet` (`apps/cms/models.py`) | SUPER_ADMIN/ADMIN see published and unpublished pages; all other roles and anonymous users see published pages only. |

## Views with direct role/scope checks

| View/source | Checks and role omissions |
|---|---|
| `UserViewSet` (`apps/accounts/views.py`) | Uses `UserQuerySet.for_user`; invite and assignment actions create HOD `RoleScope` rows. Authorization is delegated to `UserManagementPermission`; role display and scope creation use the primary role/requested role. |
| `GuardianViewSet` (`apps/people/views.py`) | Student list is limited to active guardians; create/update/archive is scoped by `may_manage_student` to admins, assigned UNIT_MANAGER/HOD, or the student's own account. |
| `EnrollmentViewSet.transition`, `CourseAccessViewSet` (`apps/enrollment/views.py`) | STUDENT may cancel only their own enrollment; HOD and UNIT_MANAGER transitions are scoped by the enrollment permission. Course access relies on its scoped queryset and object permission. |
| `ClassGroupViewSet`, `ClassTeacherViewSet`, `TimetableSlotViewSet` (`apps/scheduling/views.py`, `serializers.py`) | Class creation permits admins/HOD/UNIT_MANAGER in scope or a course-assigned teacher; teacher assignment management is limited to admins/HOD/UNIT_MANAGER in scope; timetable changes permit those managers or the assigned class teacher. Room departments and class scopes are validated by active role assignments. |
| `AcademicViewSet`, `CourseViewSet` (`apps/academics/views.py`) | Course create/update checks HOD `RoleScope`, UNIT_MANAGER unit IDs, then `may_manage_course` (admin/HOD/UNIT_MANAGER/teacher). DIRECTOR/AUDITOR/BURSAR/CASHIER/STUDENT cannot manage. |
| `AttendanceSessionViewSet.open` (`apps/attendance/views.py`) | Admin may open any class; HOD, UNIT_MANAGER and TEACHER are limited to their assigned department, unit or class respectively. |
| `AssessmentViewSet`, `GradeViewSet`, `GradebookView` (`apps/assessment/views.py`) | Assessment management allows admin/HOD/teacher; grade review allows admin/HOD; gradebook branches on STUDENT/TEACHER/HOD primary role. UNIT_MANAGER, AUDITOR, BURSAR and CASHIER are omitted from these academic operations. |
| `StudentTranscriptView` (`apps/assessment/transcripts.py`) | STUDENT self, SUPER_ADMIN/ADMIN/DIRECTOR globally, HOD by department. Other roles, including UNIT_MANAGER/AUDITOR/BURSAR/CASHIER/TEACHER, are denied; primary role only. |
| `FileStorageViewSet._may_download` (`apps/files/views.py`) | Published course assets are public; otherwise admins pass, HOD must have department scope, and `may_manage_course` covers UNIT_MANAGER/teacher. Other roles are denied; checks use primary role. |

## Findings

1. The documented G1 failure was confirmed in the initial audit. People, enrollment, scheduling and attendance have since been migrated; remaining AC3 app migrations and the authorization matrix are pending.
2. Authorization policy is inconsistent by layer. The generic unit queryset accepts any unit assignment, while concrete querysets often discard UNIT_MANAGER, AUDITOR or BURSAR; permission classes then apply a different role list.
3. Several remaining permission/view/queryset branches use the single primary `user.role`; multi-role users can lose a secondary role's scope or capability. The completed people, enrollment, scheduling and attendance migrations combine role-specific scopes.
4. Resolved in AC3 scheduling: the UNIT_MANAGER room filter now scopes through `Room.department__unit`, avoiding the nonexistent `Room.course` relation.
5. The complete actor-by-unit authorization matrix and the remaining AC3 app migrations are still pending guide items.
