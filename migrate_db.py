#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from hcr2.db.connection import DB_PATH
from hcr2.db.migrations import apply_migrations


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply HCR2 SQLite database migrations.")
    parser.add_argument(
        "--db",
        default=str(DB_PATH),
        help=f"SQLite database path (default: {DB_PATH})",
    )
    args = parser.parse_args()

    applied = apply_migrations(Path(args.db))
    if not applied:
        print("ℹ️  Database already up to date.")
        return

    for filename in applied:
        print(f"✅ Applied migration {filename}")


if __name__ == "__main__":
    main()
