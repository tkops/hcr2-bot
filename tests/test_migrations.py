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

            expected = [migration.path.name for migration in available_migrations()]
            self.assertEqual(first, expected)
            self.assertEqual(second, [])

            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle'")
                self.assertEqual(cur.fetchone()[0], "vehicle")
                cur.execute("SELECT version FROM schema_migrations ORDER BY version")
                self.assertEqual(
                    [row[0] for row in cur.fetchall()],
                    [migration.version for migration in available_migrations()],
                )

    def test_restrict_migration_blocks_orphaning_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "hcr2.db"
            apply_migrations(db_path)

            with sqlite3.connect(db_path) as conn:
                conn.executescript(
                    """
                    INSERT INTO players (id, name, team) VALUES (1, 'Alice', 'PLTE');
                    INSERT INTO season (number, name, start, division) VALUES (2, 'S', '2021-06-01', 'D');
                    INSERT INTO teamevent (id, name, iso_year, iso_week, tracks, max_score_per_track)
                        VALUES (1, 'T', 2021, 21, 4, 15000);
                    INSERT INTO match (id, teamevent_id, season_number, start, opponent)
                        VALUES (1, 1, 2, '2021-06-05', 'R');
                    INSERT INTO matchscore (id, match_id, player_id, score, points)
                        VALUES (1, 1, 1, 100, 10);
                    INSERT INTO donation (player_id, date, total) VALUES (1, '2026-01-01', 5);
                    """
                )

            with sqlite3.connect(db_path) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                for statement in (
                    "DELETE FROM players WHERE id = 1",
                    "DELETE FROM match WHERE id = 1",
                    "DELETE FROM season WHERE number = 2",
                    "DELETE FROM teamevent WHERE id = 1",
                ):
                    with self.subTest(statement=statement):
                        with self.assertRaises(sqlite3.IntegrityError):
                            conn.execute(statement)

                # The vehicle mapping is not result data and still cascades.
                conn.execute("INSERT INTO vehicle (id, name, shortname) VALUES (1, 'V', 'v')")
                conn.execute("INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (1, 1)")
                conn.execute("DELETE FROM vehicle WHERE id = 1")
                self.assertEqual(
                    conn.execute("SELECT count(*) FROM teamevent_vehicle").fetchone()[0], 0
                )
