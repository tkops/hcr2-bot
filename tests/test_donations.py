from __future__ import annotations

import sqlite3

from modules import donations
from tests.support import TemporaryDatabaseTestCase


class DonationTests(TemporaryDatabaseTestCase):
    def test_donations_add_upserts_edit_and_lists_entries(self) -> None:
        add_output = self.capture_stdout(donations.handle_command, "add", ["1", "2025-11-15", "1200"])
        self.assertIn("✅ Donation snapshot added for player 1 on 2025-11-15", add_output)

        upsert_output = self.capture_stdout(
            donations.handle_command,
            "add",
            ["--player", "1", "--date", "2025-11-15", "--total", "1500"],
        )
        self.assertIn("total: 1500", upsert_output)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT id, total FROM donation WHERE player_id = 1 AND date = '2025-11-15'").fetchone()
        self.assertIsNotNone(row)
        donation_id, total = row
        self.assertEqual(total, 1500)

        edit_output = self.capture_stdout(donations.handle_command, "edit", ["--id", str(donation_id), "1800"])
        self.assertIn(f"✅ Donation {donation_id} updated for player 1 on 2025-11-15: 1500 -> 1800", edit_output)

        dates_output = self.capture_stdout(donations.handle_command, "list", [])
        self.assertIn("📅 Donation dates:", dates_output)
        self.assertIn("2025-11-15", dates_output)
        self.assertIn("1", dates_output)

        entries_output = self.capture_stdout(donations.handle_command, "list", ["--date", "2025-11-15"])
        self.assertIn("📋 Donations for 2025-11-15:", entries_output)
        self.assertIn("Alice", entries_output)
        self.assertIn("1.8K", entries_output)

    def test_donations_show_and_index_outputs(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO match (id, teamevent_id, season_number, start, opponent, score_ladys, score_opponent)
                VALUES (2, 1, 2, '2025-11-05', 'Future Rivals', 200, 100)
                """
            )
            conn.execute(
                """
                INSERT INTO matchscore (id, match_id, player_id, score, points, absent, checkin)
                VALUES (2, 2, 1, 52000, 220, 0, 1)
                """
            )
            conn.executemany(
                "INSERT INTO donation (player_id, date, total) VALUES (?, ?, ?)",
                [
                    (1, "2025-11-01", 300),
                    (1, "2025-11-15", 900),
                ],
            )

        player_output = self.capture_stdout(donations.handle_command, "show", ["1"])
        self.assertIn("📌 Donations for Alice (ID 1):", player_output)
        self.assertIn("2025-11-15", player_output)
        self.assertIn("0.6K", player_output)

        all_output = self.capture_stdout(donations.handle_command, "show", [])
        self.assertIn("📊 Donations (K):", all_output)
        self.assertIn("Alice", all_output)
        self.assertIn("0.9K", all_output)

        index_output = self.capture_stdout(donations.handle_command, "stats", [])
        self.assertIn("📊 Donation index from 2025-11-01 to 2025-11-15:", index_output)
        self.assertIn("Alice", index_output)
        self.assertIn("150.0", index_output)

        under_output = self.capture_stdout(donations.handle_command, "under", [])
        self.assertIn("ℹ️ No players with donation index below 100 in team PLTE.", under_output)
