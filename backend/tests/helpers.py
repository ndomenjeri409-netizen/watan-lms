import os
import unittest

from django.db import connection

from apps.accounts.models import User
from apps.accounts.roles import UNIT_SCOPED_ROLES
from apps.org.models import BusinessUnit

REQUIRE_PG = os.environ.get("REQUIRE_POSTGRES_TESTS") == "1"


def postgres_only(test):
    """Skip on SQLite locally; require PostgreSQL when configured for CI."""
    if REQUIRE_PG:

        def wrapper(*args, **kwargs):
            assert connection.vendor == "postgresql", (
                "REQUIRE_POSTGRES_TESTS=1 but the database is not PostgreSQL"
            )
            return test(*args, **kwargs)

        wrapper.__name__ = test.__name__
        wrapper.__doc__ = test.__doc__
        return wrapper
    return unittest.skipUnless(connection.vendor == "postgresql", "PostgreSQL only")(
        test
    )


def create_role_user(firebase_uid, role, **extra):
    if role in UNIT_SCOPED_ROLES and "unit" not in extra:
        extra["unit"], _ = BusinessUnit.objects.get_or_create(
            code="WTI",
            defaults={
                "name": "Watan Training Institute",
                "kind": BusinessUnit.Kind.ACADEMIC,
            },
        )
    return User.objects.create_user(firebase_uid, role=role, **extra)
