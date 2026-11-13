import re
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION_SOURCE_DIRS = (
    BACKEND_ROOT / "apps",
    BACKEND_ROOT / "common",
)
PRIMARY_ROLE_ACCESS = re.compile(r"\b(?:request\.)?user\.role\b")
DISPLAY_ONLY_ROLE_PATH = Path("apps/accounts/views.py")
DISPLAY_ONLY_ROLE_LINE = '"role": user.role,'


class PrimaryRoleAuthorizationLintTests(unittest.TestCase):
    def test_permissions_views_and_models_do_not_use_primary_role_for_auth(self):
        violations = []
        patterns = ("permissions.py", "views.py", "models.py")

        for source_dir in AUTHORIZATION_SOURCE_DIRS:
            for pattern in patterns:
                for path in source_dir.rglob(pattern):
                    source = path.read_text(encoding="utf-8")
                    for line_number, line in enumerate(source.splitlines(), start=1):
                        if not PRIMARY_ROLE_ACCESS.search(line):
                            continue
                        relative_path = path.relative_to(BACKEND_ROOT)
                        if (
                            relative_path == DISPLAY_ONLY_ROLE_PATH
                            and line.strip() == DISPLAY_ONLY_ROLE_LINE
                        ):
                            continue
                        violations.append(f"{relative_path}:{line_number}")

        self.assertEqual(
            violations,
            [],
            "Authorization must use assignment-aware helpers, not user.role: "
            + ", ".join(violations),
        )
