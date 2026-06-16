from __future__ import annotations

import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hcr2.db import connection
from hcr2.db.migrations import apply_migrations


class TemporaryDatabaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "hcr2.db"

        apply_migrations(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO vehicle (id, name, shortname) VALUES (?, ?, ?)",
                [
                    (1, "Hill Climber", "hc"),
                    (2, "Rally Car", "rc"),
                ],
            )
            conn.executemany(
                "INSERT INTO season (number, name, start, division) VALUES (?, ?, ?, ?)",
                [
                    (1, "May 21", "2021-05-01", "CC"),
                    (2, "Jun 21", "2021-06-01", "DIV1"),
                ],
            )
            conn.executemany(
                """
                INSERT INTO players (id, name, alias, garage_power, active, birthday, team, discord_name, is_leader)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1, "Alice", "alice", 5000, 1, "01-15", "PLTE", "alice#1", 1),
                    (2, "Betty", "betty", 4000, 0, None, "PL1", None, 0),
                ],
            )
            conn.execute(
                """
                INSERT INTO teamevent (id, name, iso_year, iso_week, tracks, max_score_per_track)
                VALUES (1, 'Teamcup', 2021, 21, 4, 15000)
                """
            )
            conn.execute(
                """
                INSERT INTO match (id, teamevent_id, season_number, start, opponent, score_ladys, score_opponent)
                VALUES (1, 1, 2, '2021-06-05', 'Rivals', 123, 111)
                """
            )
            conn.execute(
                """
                INSERT INTO matchscore (id, match_id, player_id, score, points, absent, checkin)
                VALUES (1, 1, 1, 50000, 200, 0, 1)
                """
            )

        self.db_patch = mock.patch.object(connection, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def capture_stdout(self, func, *args) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            func(*args)
        return buffer.getvalue()
