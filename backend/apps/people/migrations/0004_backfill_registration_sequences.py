import re

from django.db import migrations

_NUMBER_PATTERNS = (
    re.compile(
        r"^(?P<unit>[A-Z0-9]{2,8})/(?P<department>[A-Z0-9]{2,8})/"
        r"(?P<year>\d{4})/(?P<sequence>\d{4,})$"
    ),
    re.compile(r"^(?P<department>[A-Z0-9]{2,8})-(?P<year>\d{4})-(?P<sequence>\d{4,})$"),
)


def _parse_registration_number(value):
    for pattern in _NUMBER_PATTERNS:
        match = pattern.fullmatch(value.upper())
        if match:
            return match.groupdict()
    return None


def backfill_registration_sequences(apps, schema_editor):
    RegistrationSequence = apps.get_model("people", "RegistrationSequence")
    Student = apps.get_model("people", "Student")
    database = schema_editor.connection.alias
    unparsed = []

    for sequence in RegistrationSequence.objects.using(database).select_related(
        "department"
    ):
        if not sequence.department_id or not sequence.department.unit_id:
            raise RuntimeError(
                f"Registration sequence {sequence.pk} has no department unit."
            )
        RegistrationSequence.objects.using(database).filter(pk=sequence.pk).update(
            unit_id=sequence.department.unit_id
        )

    highest_sequences = {}
    for student in (
        Student.objects.using(database).select_related("department__unit").iterator()
    ):
        parsed = _parse_registration_number(student.registration_number)
        department = student.department
        if (
            not parsed
            or parsed["department"].upper() != department.code.upper()
            or (
                parsed.get("unit")
                and parsed["unit"].upper() != department.unit.code.upper()
            )
        ):
            unparsed.append((student.pk, student.registration_number))
            continue
        key = (department.unit_id, department.pk, int(parsed["year"]))
        highest_sequences[key] = max(
            highest_sequences.get(key, 0), int(parsed["sequence"])
        )

    for (unit_id, department_id, year), highest in highest_sequences.items():
        sequence, created = RegistrationSequence.objects.using(database).get_or_create(
            unit_id=unit_id,
            department_id=department_id,
            year=year,
            defaults={"next_number": highest + 1},
        )
        if not created and sequence.next_number < highest + 1:
            RegistrationSequence.objects.using(database).filter(pk=sequence.pk).update(
                next_number=highest + 1
            )

    if unparsed:
        print(
            "A5 registration-number migration report: "
            f"{len(unparsed)} number(s) were not parsed; values were not changed."
        )
        for student_id, registration_number in unparsed:
            print(f"  student={student_id} registration_number={registration_number}")


class Migration(migrations.Migration):
    dependencies = [
        ("people", "0003_per_unit_registration_numbers"),
    ]

    operations = [
        migrations.RunPython(
            backfill_registration_sequences, migrations.RunPython.noop
        ),
    ]
