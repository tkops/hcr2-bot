from __future__ import annotations

import sqlite3
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PRIMARY_DB_PATH = REPO_ROOT.parent / "hcr2-db" / "hcr2.db"
FALLBACK_DB_PATH = REPO_ROOT / "hcr2.db"
DB_PATH = PRIMARY_DB_PATH if PRIMARY_DB_PATH.exists() else FALLBACK_DB_PATH


def connect_path(db_path, *, row_factory=None) -> sqlite3.Connection:
    """Connect to an explicit path with foreign keys enforced.

    SQLite defaults foreign_keys to OFF per connection, which would make the
    ON DELETE RESTRICT clauses in the schema decorative.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    if row_factory is not None:
        conn.row_factory = row_factory
    return conn


def connect_db(*, row_factory=None) -> sqlite3.Connection:
    return connect_path(DB_PATH, row_factory=row_factory)


def connect_dict_db() -> sqlite3.Connection:
    return connect_db(
        row_factory=lambda cur, row: {d[0]: row[i] for i, d in enumerate(cur.description)}
    )

