from django.db import models


class Role(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    DIRECTOR = "DIRECTOR"
    HOD = "HOD"
    TEACHER = "TEACHER"
    BURSAR = "BURSAR"
    STUDENT = "STUDENT"


STAFF_ROLES = {
    Role.SUPER_ADMIN,
    Role.ADMIN,
    Role.DIRECTOR,
    Role.HOD,
    Role.TEACHER,
    Role.BURSAR,
}
ADMIN_ROLES = {Role.SUPER_ADMIN, Role.ADMIN}
