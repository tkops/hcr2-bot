#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from hcr2.db.connection import DB_PATH
from hcr2.db.migrations import apply_migrations


def create_db(db_path: str = str(DB_PATH)) -> None:
    applied = apply_migrations(Path(db_path))
    if not applied:
        print("ℹ️  No changes applied – database already up to date.")
        return

    for filename in applied:
        print(f"✅ Applied migration {filename}")


if __name__ == "__main__":
    create_db()
