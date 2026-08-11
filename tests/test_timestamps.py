from __future__ import annotations

import re
import sqlite3
import unittest

from hcr2 import timestamps
from hcr2.services import players as player_service
from tests.support import TemporaryDatabaseTestCase


class TimestampHelperTests(unittest.TestCase):
    def test_utc_timestamps_are_rendered_in_local_time(self) -> None:
        # Europe/Berlin is UTC+2 in summer, UTC+1 in winter.
        self.assertEqual(timestamps.to_local("2026-08-11 08:35:43"), "2026-08-11 10:35:43")
        self.assertEqual(timestamps.to_local("2026-01-15 08:35:43"), "2026-01-15 09:35:43")

    def test_iso_format_with_t_is_accepted(self) -> None:
        self.assertEqual(timestamps.to_local("2026-08-11T08:35:43"), "2026-08-11 10:35:43")

    def test_empty_values_become_a_placeholder(self) -> None:
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertEqual(timestamps.to_local(value), "-")

    def test_unparsable_values_are_passed_through_unchanged(self) -> None:
        self.assertEqual(timestamps.to_local("not a date"), "not a date")

    def test_utc_now_matches_the_format_sqlite_writes(self) -> None:
        self.assertRegex(timestamps.utc_now(), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_utc_now_agrees_with_sqlite_current_timestamp(self) -> None:
        """Both must be UTC, otherwise the trigger and Python disagree by hours."""
        with sqlite3.connect(":memory:") as conn:
            sqlite_now = conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]

        self.assertEqual(timestamps.utc_now()[:13], sqlite_now[:13])  # bis zur Stunde


class TimestampStorageTests(TemporaryDatabaseTestCase):
    def test_trigger_written_timestamp_is_displayed_in_local_time(self) -> None:
        player_service.edit_player(1, name="Alice Renamed")

        with sqlite3.connect(self.db_path) as conn:
            stored = conn.execute("SELECT last_modified FROM players WHERE id = 1").fetchone()[0]
            sqlite_now = conn.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]

        # The trigger writes CURRENT_TIMESTAMP, i.e. UTC in SQLite's own format.
        self.assertRegex(stored, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(stored[:13], sqlite_now[:13])
        self.assertNotEqual(timestamps.to_local(stored), stored)  # verschoben, nicht rohes UTC

    def test_player_show_prints_local_timestamps(self) -> None:
        from modules import player

        player_service.edit_player(1, name="Alice Renamed")
        output = self.capture_stdout(player.handle_command, "show", ["--id", "1"])

        with sqlite3.connect(self.db_path) as conn:
            stored = conn.execute("SELECT last_modified FROM players WHERE id = 1").fetchone()[0]

        shown = re.search(r"^Last modified\s*:\s*(.+)$", output, re.MULTILINE).group(1).strip()
        self.assertEqual(shown, timestamps.to_local(stored))
        self.assertNotEqual(shown, stored)
