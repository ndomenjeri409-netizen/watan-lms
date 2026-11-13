from django.core.management.base import BaseCommand

from apps.people.models import Student, parse_registration_number


class Command(BaseCommand):
    help = "Report student registration numbers that do not parse or match their scope."

    def handle(self, *args, **options):
        issues = []
        students = Student.objects.select_related("department__unit").order_by("pk")
        for student in students.iterator():
            parsed = parse_registration_number(student.registration_number)
            if not parsed:
                issues.append((student, "unrecognized format"))
                continue
            if (
                parsed["unit_code"]
                and parsed["unit_code"] != student.department.unit.code.upper()
            ):
                issues.append((student, "unit prefix does not match department"))
                continue
            if (
                parsed["department_code"]
                and parsed["department_code"] != student.department.code.upper()
            ):
                issues.append((student, "department prefix does not match student"))

        if not issues:
            self.stdout.write(
                self.style.SUCCESS(
                    f"All {students.count()} registration number(s) parse and match scope."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"{len(issues)} registration number(s) need review; none were changed."
            )
        )
        for student, reason in issues:
            self.stdout.write(
                f"{student.registration_number} (student {student.pk}): {reason}"
            )
