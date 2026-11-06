from django.db import models


class Role(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    DIRECTOR = "DIRECTOR"
    AUDITOR = "AUDITOR"
    UNIT_MANAGER = "UNIT_MANAGER"
    HOD = "HOD"
    TEACHER = "TEACHER"
    BURSAR = "BURSAR"
    CASHIER = "CASHIER"
    STUDENT = "STUDENT"


GLOBAL_ROLES = {
    Role.SUPER_ADMIN,
    Role.ADMIN,
    Role.DIRECTOR,
    Role.AUDITOR,
}
GLOBAL_READ_ROLES = GLOBAL_ROLES
UNIT_SCOPED_ROLES = {
    Role.UNIT_MANAGER,
    Role.HOD,
    Role.TEACHER,
    Role.CASHIER,
}
STAFF_ROLES = {
    Role.SUPER_ADMIN,
    Role.ADMIN,
    Role.DIRECTOR,
    Role.AUDITOR,
    Role.UNIT_MANAGER,
    Role.HOD,
    Role.TEACHER,
    Role.BURSAR,
    Role.CASHIER,
}
ADMIN_ROLES = {Role.SUPER_ADMIN, Role.ADMIN}
