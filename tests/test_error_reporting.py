"""An error count without a reason cannot be acted on - these pin the reasons."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import mock

import requests

from hcr2.integrations import nextcloud
from hcr2.output import sheets as sheet_output
from hcr2.services import sheets as sheet_service
from tests.support import TemporaryDatabaseTestCase


class ImportErrorReportingTests(TemporaryDatabaseTestCase):
    def test_donation_import_reports_why_a_row_failed(self) -> None:
        # player 999 does not exist -> foreign key violation now that it is enforced
        result = sheet_service.import_donation_entries(
            self.db_path, "2026-06-13", [(1, 12000), (999, 5000)]
        )

        self.assertEqual(result.added, 1)
        self.assertEqual(result.errors, 1)
        self.assertEqual(len(result.messages), 1)
        self.assertIn("donation for player 999", result.messages[0])
        self.assertIn("IntegrityError", result.messages[0])

    def test_donation_import_keeps_workbook_read_errors_in_the_report(self) -> None:
        result = sheet_service.import_donation_entries(
            self.db_path, "2026-06-13", [(1, 12000)], initial_errors=2
        )

        self.assertEqual(result.errors, 2)
        self.assertIn("2 row(s) skipped while reading the workbook", result.messages[0])

    def test_player_import_reports_why_a_row_failed(self) -> None:
        rows = [
            {"id": 1, "name": "Alice", "garage_power": 6000},
            {"id": None, "name": None, "garage_power": 1},  # name is NOT NULL
        ]

        result = sheet_service.import_player_rows(self.db_path, rows, excluded_columns=set())

        self.assertEqual(result.errors, 1)
        self.assertTrue(result.messages)
        self.assertIn("IntegrityError", result.messages[0])

    def test_import_output_lists_reasons_and_caps_the_flood(self) -> None:
        many = [f"player {i}: IntegrityError: broken" for i in range(15)]
        result = sheet_service.PlayerImportResult(
            updated=0, inserted=0, skipped=0, errors=15, messages=many
        )

        output = self.capture_stdout(sheet_output.print_player_import_result, result, "deleted")

        self.assertIn("15 errors", output)
        self.assertIn("⚠️ player 0: IntegrityError: broken", output)
        self.assertIn("⚠️ ... and 5 more", output)
        self.assertNotIn("player 12", output)


class NextcloudErrorReportingTests(TemporaryDatabaseTestCase):
    def test_network_failure_is_reported_on_stderr_without_leaking_the_account(self) -> None:
        with mock.patch.object(
            nextcloud.requests, "get", side_effect=requests.ConnectionError("http://user@host/secret")
        ):
            with mock.patch("sys.stderr") as stderr:
                result = nextcloud.download_file("Scores/x.xlsx", Path(self.tempdir.name) / "x.xlsx")

        self.assertIsNone(result)
        written = "".join(call.args[0] for call in stderr.write.call_args_list if call.args)
        self.assertIn("nextcloud: GET failed for Scores/x.xlsx", written)
        self.assertIn("ConnectionError", written)
        # The exception text carries the URL including the account name.
        self.assertNotIn("user@host", written)

    def test_http_status_is_reported_too(self) -> None:
        response = mock.Mock(status_code=404)
        with mock.patch.object(nextcloud.requests, "get", return_value=response):
            with mock.patch("sys.stderr") as stderr:
                result = nextcloud.download_file("Scores/x.xlsx", Path(self.tempdir.name) / "x.xlsx")

        self.assertIsNone(result)
        written = "".join(call.args[0] for call in stderr.write.call_args_list if call.args)
        self.assertIn("HTTP 404", written)

    def test_delete_failure_is_reported_and_still_returns_false(self) -> None:
        with mock.patch.object(nextcloud.requests, "delete", side_effect=requests.Timeout("boom")):
            with mock.patch("sys.stderr") as stderr:
                self.assertFalse(nextcloud.delete_file("Scores/x.xlsx"))

        written = "".join(call.args[0] for call in stderr.write.call_args_list if call.args)
        self.assertIn("DELETE failed", written)
        self.assertIn("Timeout", written)


class ForeignKeyEnforcementTests(TemporaryDatabaseTestCase):
    def test_connections_enforce_foreign_keys(self) -> None:
        from hcr2.db.connection import connect_db

        with connect_db() as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_orphan_scores_can_no_longer_be_created(self) -> None:
        from hcr2.db.connection import connect_db

        with self.assertRaises(sqlite3.IntegrityError):
            with connect_db() as conn:
                conn.execute(
                    "INSERT INTO matchscore (match_id, player_id, score, points) VALUES (1, 4242, 100, 10)"
                )
