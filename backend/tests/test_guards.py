from django.apps import apps
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet, ViewSetMixin

from common.scoping import ScopedViewSetMixin

UNIT_OWNED_APP_LABELS = {
    "academics",
    "assessment",
    "attendance",
    "audit",
    "assistant",
    "comms",
    "enrollment",
    "files",
    "finance",
    "org",
    "people",
    "scheduling",
}

UNIT_EXEMPT = {
    "org.BusinessUnit": "Defines the unit boundary; it is the scope root.",
    "org.Campus": "Shared campus record referenced by departments.",
    "academics.CourseModule": "Derives its unit through Course.",
    "academics.Unit": "Course-content unit; derives its business unit through CourseModule.",
    "academics.Material": "Derives its unit through its Lesson and Course.",
    "people.Student": "Person record may participate across units; enrollment is the unit scope.",
    "people.StudentDuplicateCandidate": (
        "Join row derives scope through its lookup and candidate student."
    ),
    "people.StaffProfile": "Person record may have assignments in multiple units.",
    "people.Guardian": "Derives its unit scope through the related Student.",
    "enrollment.Application": "Derives its unit through its required Department and Course.",
    "enrollment.CourseAccess": "Derives its unit through Course.",
    "files.StoredFile": "Generic file record; access is scoped by owner and linked resource.",
    "scheduling.Room": "Shared room may serve multiple units; Department is optional.",
    "scheduling.ClassGroup": "Derives its unit through Course.",
    "attendance.AttendanceSession": "Derives its unit through ClassGroup.",
    "attendance.QrToken": "Derives its unit through AttendanceSession.",
    "attendance.AttendanceRecord": "Derives its unit through AttendanceSession and Student.",
    "attendance.CheckIn": "Derives its unit through AttendanceRecord.",
    "assessment.AssessmentTemplate": "Derives its unit through Course.",
    "assessment.Assessment": "Derives its unit through its template and class.",
    "assessment.Submission": "Derives its unit through Assessment and Student.",
    "assessment.Grade": "Derives its unit through Assessment and Enrollment.",
    "assessment.GradeRevision": "Derives its unit through Grade.",
    "assessment.AssessmentAttemptGrant": "Derives its unit through Assessment and Enrollment.",
    "assessment.GradeSupersession": "Derives its unit through Grade.",
    "assessment.TranscriptVersion": "Derives its unit through Student.",
    "assessment.LegacyGradeArchive": "Preserves converted per-attempt grade history.",
    "finance.Account": "Shared chart of accounts; unit attribution belongs on journal lines.",
    "finance.CashAccount": "Uses custody_unit as its explicit unit dimension.",
    "finance.AccountingPeriod": "Shared accounting calendar; postings are checked against the period.",
    "finance.JournalEntry": "May contain multiple units; each JournalLine carries the unit.",
    "finance.Payment": "Derives its unit through Invoice.",
    "finance.Receipt": "Derives its unit through Payment and Invoice.",
    "finance.Adjustment": "Derives its unit through Invoice.",
    "finance.Refund": "Derives its unit through Payment and Invoice.",
}

API_VIEW_ALLOWLIST = {
    "apps.accounts.reports.ReportsOverviewView": (
        "Metrics use role-scoped querysets and validate any requested unit."
    ),
    "apps.accounts.views.MeView": "Reads and updates only request.user.",
    "apps.assessment.transcripts.StudentTranscriptView": (
        "Restricts students to their own transcript and staff to permitted roles/scopes."
    ),
    "apps.assessment.transcripts.TranscriptVersionListView": (
        "Restricts transcript history to a student authorized by _authorized_student."
    ),
    "apps.assessment.views.GradebookView": (
        "Resolves the course through Course.objects.for_user and applies learner checks."
    ),
    "apps.attendance.views.CheckInView": (
        "The check-in service validates the QR token and its authorized session."
    ),
    "apps.finance.views.ReceiptPdfView": (
        "Restricts receipt downloads to the student owner or an authorized finance unit."
    ),
    "apps.finance.views.StudentStatementView": (
        "Restricts statement lines to the student's units and the caller's authorized units."
    ),
    "apps.org.views.BusinessUnitListView": (
        "Lists active units assigned to the user or visible to an authorized group reader."
    ),
}

ACTION_ALLOWLIST = {
    "apps.accounts.views.UserViewSet.invite": (
        "assert_role_assignment validates the inviter's permission to grant the role/unit."
    ),
    "apps.people.views.StudentViewSet.duplicate_lookup": (
        "lookup_student_duplicate validates the single-use token and caller's unit scope."
    ),
    "apps.people.views.StudentViewSet.import_students": (
        "import_student_csv validates each row against the caller's authorized unit."
    ),
    "apps.people.views.StudentViewSet.transfer": (
        "Object permission and transfer_student validate source and target unit scope."
    ),
    "apps.files.views.FileStorageViewSet.download_url": (
        "_get_stored_file and _may_download enforce owner and resource-specific access."
    ),
    "apps.files.views.FileStorageViewSet.uploads": (
        "Creates a file for request.user after serializer policy validation."
    ),
}


def _all_subclasses(base_class):
    seen = set()
    pending = list(base_class.__subclasses__())
    while pending:
        subclass = pending.pop()
        if subclass in seen:
            continue
        seen.add(subclass)
        yield subclass
        pending.extend(subclass.__subclasses__())


def _load_api_views():
    import config.urls  # noqa: F401


def _concrete_model_viewsets():
    _load_api_views()
    return [
        viewset
        for viewset in _all_subclasses(ModelViewSet)
        if viewset.__module__.startswith("apps.")
        and getattr(viewset, "queryset", None) is not None
        and getattr(viewset.queryset, "model", None) is not None
    ]


def _models_missing_unit(models):
    return [
        model._meta.label
        for model in models
        if model._meta.app_label in UNIT_OWNED_APP_LABELS
        and not model._meta.abstract
        and not model._meta.proxy
        and not any(field.name == "unit" for field in model._meta.get_fields())
    ]


def _unscoped_actions(viewsets):
    unscoped = set()
    for viewset in viewsets:
        for name, method in viewset.__dict__.items():
            if not callable(method) or not hasattr(method, "mapping"):
                continue
            code = getattr(method, "__code__", None)
            names = set(code.co_names) if code is not None else set()
            if not names.intersection({"get_object", "get_queryset", "for_user"}):
                unscoped.add(f"{viewset.__module__}.{viewset.__name__}.{name}")
    return unscoped


def test_every_model_viewset_uses_scoped_queryset():
    violations = []
    for viewset in _concrete_model_viewsets():
        label = f"{viewset.__module__}.{viewset.__name__}"
        if not issubclass(viewset, ScopedViewSetMixin):
            violations.append(f"{label} does not inherit ScopedViewSetMixin")
        queryset = viewset.queryset.model._default_manager.get_queryset()
        if not callable(getattr(queryset, "for_user", None)):
            violations.append(f"{label} model manager has no for_user queryset")

    assert violations == [], f"Unscoped model viewsets: {violations}"


def test_actions_use_scoped_access_or_a_reasoned_allowlist():
    viewsets = _concrete_model_viewsets()
    _load_api_views()
    viewsets.extend(
        view
        for view in _all_subclasses(APIView)
        if view.__module__.startswith("apps.")
        and issubclass(view, ViewSetMixin)
        and getattr(view, "queryset", None) is not None
        and getattr(view.queryset, "model", None) is not None
        and view not in viewsets
    )
    unscoped = _unscoped_actions(viewsets)
    assert unscoped == set(ACTION_ALLOWLIST), (
        f"Actions need a scoped query or a reasoned allowlist entry. "
        f"Unscoped: {sorted(unscoped - set(ACTION_ALLOWLIST))}; "
        f"stale allowlist: {sorted(set(ACTION_ALLOWLIST) - unscoped)}"
    )
    assert all(reason.strip() for reason in ACTION_ALLOWLIST.values())


def test_non_model_api_views_have_explicit_scoping_reasons():
    _load_api_views()
    discovered = {
        f"{view.__module__}.{view.__name__}"
        for view in _all_subclasses(APIView)
        if view.__module__.startswith("apps.") and not issubclass(view, ViewSetMixin)
    }
    allowed = set(API_VIEW_ALLOWLIST)
    assert discovered == allowed, (
        f"Non-model APIViews need a reasoned allowlist entry. "
        f"Unlisted: {sorted(discovered - allowed)}; "
        f"stale allowlist: {sorted(allowed - discovered)}"
    )
    assert all(reason.strip() for reason in API_VIEW_ALLOWLIST.values())


def test_every_domain_model_has_unit_or_a_reasoned_exemption():
    models_missing_unit = set(_models_missing_unit(apps.get_models()))
    exemptions = set(UNIT_EXEMPT)
    assert models_missing_unit == exemptions, (
        f"Unit ownership needs review. Unlisted models: "
        f"{sorted(models_missing_unit - exemptions)}; stale exemptions: "
        f"{sorted(exemptions - models_missing_unit)}"
    )
    assert all(reason.strip() for reason in UNIT_EXEMPT.values())
