#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys


VERSION_RE = re.compile(r'^VERSION = "(\d+)\.(\d+)\.(\d+)"$', re.MULTILINE)
HISTORY_START = "HISTORY = ["


def bump_semver(version: str, level: str) -> str:
    major, minor, patch = (int(part) for part in version.split("."))
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown bump level: {level}")


def update_version_text(text: str, *, level: str, change: str, entry_date: str) -> tuple[str, str, str]:
    match = VERSION_RE.search(text)
    if not match:
        raise ValueError('Could not find VERSION = "X.Y.Z" line.')

    old_version = ".".join(match.groups())
    new_version = bump_semver(old_version, level)
    if f'("{new_version}",' in text:
        raise ValueError(f"Version {new_version} already exists in HISTORY.")

    updated = VERSION_RE.sub(f'VERSION = "{new_version}"', text, count=1)

    history_index = updated.find(HISTORY_START)
    if history_index == -1:
        raise ValueError("Could not find HISTORY list.")

    insert_at = history_index + len(HISTORY_START)
    history_entry = f"\n    ({json.dumps(new_version)}, {json.dumps(entry_date)}, {json.dumps(change)}),"
    updated = updated[:insert_at] + history_entry + updated[insert_at:]
    return updated, old_version, new_version


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bump version.py and prepend a HISTORY entry.")
    parser.add_argument("level", choices=["major", "minor", "patch"], help="Semantic version component to bump.")
    parser.add_argument("change", help="Short changelog text for HISTORY.")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="History date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--version-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "version.py",
        help="Path to version.py. Mainly useful for tests.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    change = args.change.strip()
    if not change:
        print("Change text must not be empty.", file=sys.stderr)
        return 2

    version_file = args.version_file
    try:
        original = version_file.read_text(encoding="utf-8")
        updated, old_version, new_version = update_version_text(
            original,
            level=args.level,
            change=change,
            entry_date=args.date,
        )
        version_file.write_text(updated, encoding="utf-8")
    except OSError as exc:
        print(f"Could not update {version_file}: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Bumped version: {old_version} -> {new_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
