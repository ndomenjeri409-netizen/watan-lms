import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY_EXTENSIONS = {".png", ".jpg", ".ico", ".woff", ".pdf", ".zip"}


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode:
        print(
            result.stderr.decode(errors="replace").strip()
            or "Could not list tracked files.",
            file=sys.stderr,
        )
        return 1

    checked = 0
    errors = []
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = ROOT / Path(raw_path.decode(errors="surrogateescape"))
        if path.suffix.lower() in BINARY_EXTENSIONS or not path.exists():
            continue
        try:
            content = path.read_bytes()
        except OSError as exc:
            errors.append(
                f"{path.relative_to(ROOT).as_posix()}: cannot read file ({exc})"
            )
            continue
        checked += 1
        if b"\x00" in content:
            errors.append(f"{path.relative_to(ROOT).as_posix()}: contains NUL bytes")

    if errors:
        print("Tracked-file NUL check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Tracked-file NUL check passed ({checked} text files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
