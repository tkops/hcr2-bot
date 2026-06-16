from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from hcr2.db.migrations import apply_migrations, available_migrations


class MigrationTests(unittest.TestCase):
    def test_initial_migration_is_available(self) -> None:
        migrations = available_migrations()
        self.assertEqual(migrations[0].path.name, "0001_initial_schema.sql")

    def test_apply_migrations_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "hcr2.db"
            first = apply_migrations(db_path)
            second = apply_migrations(db_path)

            self.assertEqual(first, ["0001_initial_schema.sql"])
            self.assertEqual(second, [])

            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle'")
                self.assertEqual(cur.fetchone()[0], "vehicle")
                cur.execute("SELECT version FROM schema_migrations")
                self.assertEqual(cur.fetchall(), [("0001",)])
