from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path


def available_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Migration]:
    return [
        Migration(version=path.stem.split("_", 1)[0], path=path)
        for path in sorted(migrations_dir.glob("*.sql"))
        if path.name[0:4].isdigit()
    ]


def apply_migrations(db_path: Path, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    applied: list[str] = []

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        _ensure_migrations_table(conn)
        existing = _applied_versions(conn)

        for migration in available_migrations(migrations_dir):
            if migration.version in existing:
                continue
            sql = migration.path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, filename) VALUES (?, ?)",
                (migration.version, migration.path.name),
            )
            applied.append(migration.path.name)

        conn.execute("PRAGMA foreign_keys=ON")

    return applied


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations(
            version TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    cur = conn.cursor()
    cur.execute("SELECT version FROM schema_migrations")
    return {row[0] for row in cur.fetchall()}

