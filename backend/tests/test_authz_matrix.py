import json
import re
from pathlib import Path

import yaml
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from tests.helpers import create_role_user

MATRIX_PATH = Path(__file__).with_name("authz_matrix.yaml")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MATRIX_ID = "00000000-0000-0000-0000-000000000001"


def discover_api_operations(patterns=None, prefix=""):
    patterns = patterns if patterns is not None else get_resolver().url_patterns
    operations = set()

    for pattern in patterns:
        child_regex = pattern.pattern.regex.pattern.lstrip("^")
        route_regex = prefix + child_regex
        if isinstance(pattern, URLResolver):
            operations.update(
                discover_api_operations(pattern.url_patterns, route_regex)
            )
            continue
        if (
            not isinstance(pattern, URLPattern)
            or not route_regex.startswith("api/v1/")
            or "(?P<format>" in route_regex
        ):
            continue

        route = route_regex.removesuffix(r"\Z").rstrip("$")
        route = re.sub(
            r"\(\?P<([^>]+)>[^)]*\)",
            lambda match: (
                "{" + ("id" if match.group(1) == "pk" else match.group(1)) + "}"
            ),
            route,
        )
        route = route.replace(r"\-", "-")
        if route == "api/v1/":
            continue

        actions = getattr(pattern.callback, "actions", None)
        view_class = getattr(
            pattern.callback,
            "cls",
            getattr(pattern.callback, "view_class", None),
        )
        allowed_methods = set(getattr(view_class, "http_method_names", ()))
        if actions:
            methods = {
                method: action
                for method, action in actions.items()
                if method.lower() in allowed_methods
                and method.lower() in {"get", "post", "put", "patch", "delete"}
            }
        else:
            if view_class is None:
                continue
            methods = {
                method: method
                for method in view_class.http_method_names
                if method in {"get", "post", "put", "patch", "delete"}
                and hasattr(view_class, method)
            }

        operations.update((method.upper(), f"/{route}") for method in methods)

    return operations


def concrete_path(route):
    return re.sub(
        r"\{([^}]+)}",
        lambda match: "authz-matrix-missing" if match.group(1) == "slug" else MATRIX_ID,
        route,
    )


class AuthorizationMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with MATRIX_PATH.open(encoding="utf-8") as matrix_file:
            cls.matrix = yaml.safe_load(matrix_file)

    def test_matrix_covers_every_api_operation(self):
        declared = {
            (entry["method"], entry["path"]) for entry in self.matrix["endpoints"]
        }
        discovered = discover_api_operations()

        self.assertEqual(
            declared,
            discovered,
            msg=(
                f"Missing from matrix: {sorted(discovered - declared)}\n"
                f"Stale matrix entries: {sorted(declared - discovered)}"
            ),
        )
        self.assertEqual(
            set(self.matrix["actors"]),
            set(self.matrix["read_only_write_status"]),
        )
        for entry in self.matrix["endpoints"]:
            expected = (
                self.matrix["read_only_write_status"]
                if entry["method"] in WRITE_METHODS
                else {}
            )
            self.assertEqual(entry.get("expected", {}), expected, entry)

    def test_director_and_auditor_cannot_write_to_any_api_endpoint(self):
        write_entries = [
            entry
            for entry in self.matrix["endpoints"]
            if entry["method"] in WRITE_METHODS
        ]
        actors = {
            profile: create_role_user(
                f"authz-matrix-{profile.lower()}", role=actor["role"]
            )
            for profile, actor in self.matrix["actors"].items()
        }
        client = APIClient()

        for entry in write_entries:
            for role, expected_status in entry["expected"].items():
                with self.subTest(
                    role=role,
                    method=entry["method"],
                    route=entry["path"],
                ):
                    client.force_authenticate(actors[role])
                    response = client.generic(
                        entry["method"],
                        concrete_path(entry["path"]),
                        data=json.dumps({}),
                        content_type="application/json",
                    )
                    self.assertEqual(
                        response.status_code,
                        expected_status,
                        response.content,
                    )
