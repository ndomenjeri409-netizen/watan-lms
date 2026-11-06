import json

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder

from apps.audit.models import AuditLog

UNIT_LOOKUP_PATHS = {
    "academics.course": ("department__unit",),
    "academics.coursemodule": ("course__department__unit",),
    "academics.unit": ("module__course__department__unit",),
    "academics.lesson": ("unit__module__course__department__unit",),
    "academics.material": ("lesson__unit__module__course__department__unit",),
    "assessment.assessment": ("course__department__unit",),
    "assessment.submission": (
        "student__department__unit",
        "assessment__course__department__unit",
    ),
    "assessment.grade": (
        "submission__student__department__unit",
        "submission__assessment__course__department__unit",
    ),
    "attendance.attendancesession": ("class_group__course__department__unit",),
    "attendance.qrtoken": ("session__class_group__course__department__unit",),
    "attendance.attendancerecord": ("student__department__unit",),
    "attendance.checkin": ("record__student__department__unit",),
    "enrollment.application": ("department__unit", "course__department__unit"),
    "enrollment.enrollment": ("student__department__unit", "course__department__unit"),
    "enrollment.courseaccess": (
        "student__department__unit",
        "course__department__unit",
    ),
    "finance.adjustment": ("invoice__unit",),
    "finance.cashaccount": ("custody_unit",),
    "finance.payment": ("invoice__unit",),
    "finance.receipt": ("payment__invoice__unit",),
    "finance.refund": ("payment__invoice__unit",),
    "org.department": ("unit",),
    "org.program": ("department__unit",),
    "people.guardian": ("student__department__unit",),
    "people.registrationsequence": ("department__unit",),
    "people.staffprofile": ("department__unit",),
    "people.student": ("department__unit",),
    "scheduling.classgroup": ("course__department__unit",),
    "scheduling.room": ("department__unit",),
    "scheduling.timetableslot": ("class_group__course__department__unit",),
}


def _resolve_path(instance, path):
    value = instance
    for relation in path.split("__"):
        value = getattr(value, relation, None)
        if value is None:
            return None
    if (
        getattr(getattr(value, "_meta", None), "label_lower", None)
        != "org.businessunit"
    ):
        return None
    return value


def get_object_unit(instance):
    model_label = instance._meta.label_lower
    if model_label == "org.businessunit":
        return instance

    try:
        unit_field = instance._meta.get_field("unit")
    except FieldDoesNotExist:
        unit_field = None
    if (
        unit_field is not None
        and getattr(unit_field.related_model, "_meta", None) is not None
        and unit_field.related_model._meta.label_lower == "org.businessunit"
    ):
        return getattr(instance, "unit", None)

    if model_label == "accounts.user":
        unit_ids = set(
            instance.assignments.filter(is_active=True, unit__isnull=False).values_list(
                "unit_id", flat=True
            )
        )
        unit_ids.update(
            instance.role_scopes.filter(department__unit__isnull=False).values_list(
                "department__unit_id", flat=True
            )
        )
        if len(unit_ids) == 1:
            return apps.get_model("org", "BusinessUnit").objects.get(pk=unit_ids.pop())
        return None

    if model_label == "finance.journalentry":
        unit_ids = set(instance.lines.values_list("unit_id", flat=True).distinct())
        if len(unit_ids) == 1:
            return apps.get_model("org", "BusinessUnit").objects.get(pk=unit_ids.pop())
        return None

    paths = UNIT_LOOKUP_PATHS.get(model_label, ())
    units = {
        unit.pk: unit
        for path in paths
        if (unit := _resolve_path(instance, path)) is not None
    }
    return next(iter(units.values())) if len(units) == 1 else None


def get_object_audit_scope(instance):
    unit = get_object_unit(instance)
    return unit, unit is None


def record_audit(
    *,
    actor=None,
    action,
    obj,
    unit=None,
    group_level=False,
    before=None,
    after=None,
    system_label=None,
    meta=None,
):
    if actor is not None and system_label is not None:
        raise ValueError("Provide either an actor or a system label, not both.")
    if actor is None and not (system_label and system_label.strip()):
        raise ValueError("An actor or non-empty system label is required.")
    if group_level and unit is not None:
        raise ValueError("Group-level audit entries cannot have a unit.")

    if unit is None and not group_level:
        unit = get_object_unit(obj)
    if unit is None and not group_level:
        raise ValueError(
            "The audit object has no unique unit; provide a unit or group_level=True."
        )

    return AuditLog.objects.create(
        actor=actor,
        unit=unit,
        scope=AuditLog.Scope.GROUP if group_level else AuditLog.Scope.UNIT,
        actor_kind=(
            AuditLog.ActorKind.SYSTEM if actor is None else AuditLog.ActorKind.USER
        ),
        actor_label=system_label.strip() if system_label else "",
        action=action,
        object_type=obj._meta.label,
        object_id=str(obj.pk),
        before=json.loads(json.dumps(before or {}, cls=DjangoJSONEncoder)),
        after=json.loads(json.dumps(after or {}, cls=DjangoJSONEncoder)),
        meta=json.loads(json.dumps(meta or {}, cls=DjangoJSONEncoder)),
    )
