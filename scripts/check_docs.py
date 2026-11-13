from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def main() -> int:
    errors = []
    files = sorted((*DOCS.glob("*.md"), *DOCS.glob("*.csv")))

    for path in files:
        try:
            content = path.read_bytes()
        except OSError as exc:
            errors.append(f"{path.relative_to(ROOT)}: cannot read file ({exc})")
            continue

        if not content:
            errors.append(f"{path.relative_to(ROOT)}: file is empty")
        if b"\x00" in content:
            errors.append(f"{path.relative_to(ROOT)}: contains NUL bytes")

    progress = DOCS / "PROGRESS.md"
    try:
        progress_text = progress.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        errors.append(f"docs/PROGRESS.md: cannot read as UTF-8 ({exc})")
    else:
        for heading in ("Sprints", "Section A"):
            if heading not in progress_text:
                errors.append(f"docs/PROGRESS.md: missing required heading text {heading!r}")

    if errors:
        print("Documentation integrity check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Documentation integrity check passed ({len(files)} Markdown/CSV files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
