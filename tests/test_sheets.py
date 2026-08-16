from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import mock

from hcr2.exporters import excel as excel_exporter
from hcr2.services import sheets as sheet_service
from modules import sheet
from tests.support import TemporaryDatabaseTestCase


class SheetTests(TemporaryDatabaseTestCase):
    def test_sheet_service_builds_paths_and_parses_k_amounts(self) -> None:
        filename = sheet_service.match_sheet_filename(7, "Team Cup!", "Fast Opps #1")
        self.assertEqual(filename, "7_Team_Cup_Fast_Opps_1.xlsx")
        self.assertEqual(
            sheet_service.match_sheet_remote_path_for_filename(62, filename).as_posix(),
            "Power-Ladys-Scores/Team-Event/S62/7_Team_Cup_Fast_Opps_1.xlsx",
        )
        self.assertEqual(sheet_service.match_sheet_tmp_path(filename), Path("tmp") / filename)
        self.assertEqual(sheet_service.scores_web_url(62), "https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path=/Scores/Team-Event/S62")
        self.assertEqual(sheet_service.to_k(12500), 12.5)
        self.assertEqual(sheet_service.parse_k_amount("12,5k"), 12500)
        self.assertEqual(sheet_service.parse_k_amount(7), 7000)
        self.assertIsNone(sheet_service.parse_k_amount("-1"))

    def test_sheet_service_orchestrates_sheet_files(self) -> None:
        local_path = Path("tmp") / "7_Event_Opponent.xlsx"
        with mock.patch.object(sheet_service, "upload_file", return_value=("url", True)) as upload, \
                mock.patch.object(sheet_service, "download_file", return_value=local_path) as download, \
                mock.patch.object(sheet_service, "delete_file", return_value=True) as delete:
            self.assertEqual(sheet_service.upload_match_sheet(local_path, 62, local_path.name), ("url", True))
            self.assertEqual(sheet_service.download_match_sheet(62, local_path.name, local_path), local_path)
            self.assertEqual(sheet_service.cleanup_imported_workbook(local_path, sheet_service.PLAYERS_REMOTE_PATH), "deleted")

        upload.assert_called_once_with(
            local_path,
            Path("Power-Ladys-Scores") / "Team-Event" / "S62" / local_path.name,
            overwrite=False,
        )
        download.assert_called_once_with(Path("Power-Ladys-Scores") / "Team-Event" / "S62" / local_path.name, local_path)
        delete.assert_called_once_with(sheet_service.PLAYERS_REMOTE_PATH)

    def test_sheet_service_imports_player_rows(self) -> None:
        rows = [
            {"id": 1, "name": "Alice Prime", "garage_power": 5100, "active": "true", "is_leader": "no"},
            {"id": 99, "name": "Cara", "alias": "cara", "garage_power": 3000, "active": None},
            {"id": 1, "name": "Alice Prime", "garage_power": 5100, "active": "true", "is_leader": "no"},
            {"id": 100, "garage_power": 2000},
        ]

        result = sheet_service.import_player_rows(
            self.db_path,
            rows,
            excluded_columns=sheet.EXCLUDED_PLAYER_COLS,
        )

        self.assertEqual(result.updated, 1)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.errors, 1)
        with sqlite3.connect(self.db_path) as conn:
            alice = conn.execute("SELECT name, garage_power, is_leader FROM players WHERE id = 1").fetchone()
            cara = conn.execute("SELECT name, team, active FROM players WHERE alias = 'cara'").fetchone()
        self.assertEqual(alice, ("Alice Prime", 5100, 0))
        self.assertEqual(cara, ("Cara", "PLTE", 1))

    def test_sheet_service_imports_players_workbook_with_cleanup(self) -> None:
        workbook = excel_exporter.build_players_workbook(
            ["id", "name", "garage_power"],
            [(1, "Alice Prime", 5100)],
        )
        local_path = Path(self.tempdir.name) / "Ladys.xlsx"
        workbook.save(local_path)

        with mock.patch.object(sheet_service, "delete_file", return_value=True) as delete_remote:
            outcome = sheet_service.import_players_workbook(
                self.db_path,
                workbook_reader=excel_exporter.read_players_workbook,
                excluded_columns=sheet.EXCLUDED_PLAYER_COLS,
                local_xlsx=local_path,
            )

        self.assertEqual(outcome.status, "IMPORTED")
        self.assertEqual(outcome.cleanup_status, "deleted")
        self.assertEqual(outcome.result.updated, 1)
        self.assertFalse(local_path.exists())
        delete_remote.assert_called_once_with(sheet_service.PLAYERS_REMOTE_PATH)

    def test_sheet_service_builds_player_export_data(self) -> None:
        export_data = sheet_service.get_player_export_data(
            self.db_path,
            excluded_columns=sheet.EXCLUDED_PLAYER_COLS,
        )

        self.assertIsNotNone(export_data)
        self.assertIn("id", export_data.columns)
        self.assertIn("name", export_data.columns)
        self.assertNotIn("team", export_data.columns)
        self.assertEqual(len(export_data.rows), 1)
        self.assertEqual(export_data.rows[0][export_data.columns.index("name")], "Alice")

    def test_sheet_service_exports_players_workbook_with_cleanup(self) -> None:
        out_path = Path(self.tempdir.name) / "Ladys.xlsx"

        with mock.patch.object(sheet_service, "upload_file", return_value=("url", True)) as upload:
            outcome = sheet_service.export_players_workbook(
                self.db_path,
                workbook_builder=excel_exporter.build_players_workbook,
                workbook_saver=excel_exporter.save_workbook,
                excluded_columns=sheet.EXCLUDED_PLAYER_COLS,
                out_path=out_path,
            )

        self.assertEqual(outcome.status, "EXPORTED")
        self.assertEqual(outcome.label, "Power-Ladys-Scores/Ladys/Ladys.xlsx")
        self.assertTrue(outcome.created)
        self.assertFalse(out_path.exists())
        upload.assert_called_once_with(out_path, sheet_service.PLAYERS_REMOTE_PATH, overwrite=True)

    def test_sheet_service_builds_donation_export_rows(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO donation (player_id, date, total) VALUES (1, '2026-06-01', 12000)")
            conn.execute("INSERT INTO donation (player_id, date, total) VALUES (1, '2026-06-13', 15000)")
            conn.execute(
                """
                INSERT INTO players (id, name, alias, garage_power, active, team)
                VALUES (3, 'Cara', 'cara', 3000, 1, 'PLTE')
                """
            )

        rows = sheet_service.get_donation_export_rows(self.db_path)

        self.assertEqual(rows, [(1, "Alice", 15000), (3, "Cara", 0)])

    def test_sheet_service_exports_donations_workbook_with_cleanup(self) -> None:
        out_path = Path(self.tempdir.name) / "Donations.xlsx"

        with mock.patch.object(sheet_service, "upload_file", return_value=("url", False)) as upload:
            outcome = sheet_service.export_donations_workbook(
                self.db_path,
                workbook_builder=excel_exporter.build_donations_workbook,
                workbook_saver=excel_exporter.save_workbook,
                today="2026-06-15",
                out_path=out_path,
            )

        self.assertEqual(outcome.status, "EXPORTED")
        self.assertEqual(outcome.label, "Power-Ladys-Scores/Donations/Donations.xlsx")
        self.assertFalse(outcome.created)
        self.assertFalse(out_path.exists())
        upload.assert_called_once_with(out_path, sheet_service.DONATIONS_REMOTE_PATH, overwrite=True)

    def test_sheet_service_imports_donations_workbook_with_cleanup(self) -> None:
        workbook = excel_exporter.build_donations_workbook([(1, "Alice", 12000)], "2026-06-13")
        workbook.active["C4"] = "13k"
        local_path = Path(self.tempdir.name) / "Donations.xlsx"
        workbook.save(local_path)

        with mock.patch.object(sheet_service, "delete_file", return_value=True) as delete_remote:
            outcome = sheet_service.import_donations_workbook(
                self.db_path,
                workbook_reader=excel_exporter.read_donations_workbook,
                local_xlsx=local_path,
            )

        self.assertEqual(outcome.status, "IMPORTED")
        self.assertEqual(outcome.cleanup_status, "deleted")
        self.assertEqual(outcome.result.added, 1)
        self.assertEqual(outcome.result.errors, 0)
        self.assertFalse(local_path.exists())
        delete_remote.assert_called_once_with(sheet_service.DONATIONS_REMOTE_PATH)

    def test_sheet_service_builds_match_export_data(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO players (id, name, alias, garage_power, active, team)
                VALUES (3, 'Cara', 'cara', 3000, 1, 'PLTE')
                """
            )
            conn.execute(
                """
                INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin)
                VALUES (1, 3, 60000, 250, 0, 1)
                """
            )

        export_data = sheet_service.get_match_export_data(self.db_path, 1)

        self.assertIsNotNone(export_data)
        self.assertEqual(export_data.match, (1, "2021-06-05", 2, "Rivals", "Teamcup"))
        self.assertEqual([player[1] for player in export_data.players], ["Cara", "Alice"])

    def test_sheet_service_exports_match_sheet_workflow(self) -> None:
        output_path = Path(self.tempdir.name) / "scores"

        with mock.patch.object(sheet_service, "upload_file", return_value=("url", True)) as upload:
            outcome = sheet_service.export_match_sheet(
                self.db_path,
                1,
                output_path=output_path,
                workbook_builder=excel_exporter.build_match_sheet_workbook,
                workbook_saver=excel_exporter.save_workbook,
                absent_checker=lambda _day, _frm, _until: False,
            )

        expected_local = output_path / "Team-Event" / "S2" / "1_Teamcup_Rivals.xlsx"
        self.assertEqual(outcome.status, "EXPORTED")
        self.assertEqual(outcome.markdown_link, "[1_Teamcup_Rivals.xlsx](https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path=/Scores/Team-Event/S2)")
        self.assertTrue(outcome.created)
        self.assertFalse(expected_local.exists())
        upload.assert_called_once_with(
            expected_local,
            Path("Power-Ladys-Scores") / "Team-Event" / "S2" / "1_Teamcup_Rivals.xlsx",
            overwrite=False,
        )

    def test_sheet_service_imports_match_sheet_workflow(self) -> None:
        workbook = excel_exporter.Workbook()
        ws = workbook.active
        ws["C2"] = 330
        ws["D2"] = 220
        ws.append(["MatchID", "PlayerID", "Player", "Score", "Points", "Absent", "Checkin"])
        ws.append([1, 1, "Alice", 51000, 210, "false", "true"])
        ws.append([1, 2, "Betty", 42000, 120, "true", "false"])
        local_path = Path(self.tempdir.name) / "1_Teamcup_Rivals.xlsx"
        workbook.save(local_path)

        with mock.patch.object(sheet_service, "download_match_sheet", return_value=local_path) as download:
            outcome = sheet_service.import_match_sheet(
                self.db_path,
                1,
                workbook_reader=excel_exporter.read_match_sheet_workbook,
            )

        self.assertEqual(outcome.status, "IMPORTED")
        self.assertEqual(outcome.filename, "1_Teamcup_Rivals.xlsx")
        self.assertEqual(outcome.result.imported, 2)
        self.assertEqual(outcome.result.changed, 2)
        self.assertFalse(local_path.exists())
        download.assert_called_once_with(2, "1_Teamcup_Rivals.xlsx", Path("tmp") / "1_Teamcup_Rivals.xlsx")

    def test_sheet_service_imports_donation_entries_without_subprocess(self) -> None:
        result = sheet_service.import_donation_entries(
            self.db_path,
            "2026-06-13",
            [(1, 12000), (2, 8000)],
            initial_errors=1,
        )

        self.assertEqual(result.added, 2)
        self.assertEqual(result.errors, 1)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT player_id, date, total
                FROM donation
                WHERE date = '2026-06-13'
                ORDER BY player_id
                """
            ).fetchall()
        self.assertEqual(rows, [(1, "2026-06-13", 12000), (2, "2026-06-13", 8000)])

    def test_sheet_service_applies_match_sheet_entries_without_subprocess(self) -> None:
        entries = [
            {"pid": 1, "score": 51000, "points": 210, "absent": 0, "checkin": 1},
            {"pid": 2, "score": 42000, "points": 120, "absent": 1, "checkin": 0},
        ]

        result = sheet_service.apply_match_sheet_entries(
            match_id=1,
            entries=entries,
            score_ladys=330,
            score_opponent=220,
        )

        self.assertEqual(result.imported, 2)
        self.assertEqual(result.changed, 2)
        self.assertTrue(result.score_updated)
        self.assertEqual(result.errors, 0)
        with sqlite3.connect(self.db_path) as conn:
            scores = conn.execute(
                """
                SELECT player_id, score, points, absent, checkin
                FROM matchscore
                WHERE match_id = 1
                ORDER BY player_id
                """
            ).fetchall()
            match_scores = conn.execute(
                "SELECT score_ladys, score_opponent FROM match WHERE id = 1"
            ).fetchone()
        self.assertEqual(scores, [(1, 51000, 210, 0, 1), (2, 42000, 120, 1, 0)])
        self.assertEqual(match_scores, (330, 220))

    def test_sheet_service_validates_match_sheet_rows(self) -> None:
        rows = [
            (4, (1, 1, "Alice", 51000, 210, "false", "true")),
            (5, (1, "a", "Cara", 42000, 120, "yes", "no")),
        ]

        result = sheet_service.validate_match_sheet_rows(
            lady_score=330,
            opponent_score=220,
            rows=rows,
            player_creator=lambda name: 3 if name == "Cara" else None,
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(
            result.entries,
            [
                {"row": 4, "pid": 1, "score": 51000, "points": 210, "absent": 0, "checkin": 1},
                {"row": 5, "pid": 3, "score": 42000, "points": 120, "absent": 1, "checkin": 0},
            ],
        )
        # Only the existing-ID row is a rename candidate; the 'a' row already created the player.
        self.assertEqual(result.name_updates, [{"row": 4, "pid": 1, "name": "Alice"}])

    def test_sheet_service_collects_name_updates_and_rejects_overlong_names(self) -> None:
        rows = [
            (4, (1, 1, "  Alice Cooper  ", 51000, 210, "false", "false")),
            (5, (1, 2, None, 42000, 120, "false", "false")),
            (6, (1, 3, "x" * (sheet_service.MAX_PLAYER_NAME_LEN + 1), 41000, 100, "false", "false")),
        ]

        result = sheet_service.validate_match_sheet_rows(
            lady_score=430,
            opponent_score=220,
            rows=rows,
            player_creator=lambda _name: None,
        )

        self.assertEqual(result.name_updates, [{"row": 4, "pid": 1, "name": "Alice Cooper"}])
        self.assertTrue(any("Player name too long" in error for error in result.errors))

    def test_sheet_service_applies_player_renames_from_match_sheet(self) -> None:
        result = sheet_service.apply_match_sheet_entries(
            match_id=1,
            entries=[{"pid": 1, "score": 51000, "points": 210, "absent": 0, "checkin": 1}],
            score_ladys=210,
            score_opponent=200,
            name_updates=[
                {"row": 4, "pid": 1, "name": "Alice Cooper"},
                {"row": 5, "pid": 2, "name": "Betty"},
                {"row": 6, "pid": 999, "name": "Ghost"},
            ],
        )

        self.assertEqual(result.renamed, [(1, "Alice", "Alice Cooper")])
        self.assertEqual(result.rename_errors, [])
        with sqlite3.connect(self.db_path) as conn:
            names = conn.execute("SELECT id, name FROM players ORDER BY id").fetchall()
        # 2 keeps its name (unchanged in the sheet), 999 does not exist and is ignored.
        self.assertEqual(names, [(1, "Alice Cooper"), (2, "Betty")])

    def test_sheet_service_keeps_name_when_rename_is_rejected(self) -> None:
        with mock.patch.object(
            sheet_service.player_service,
            "edit_player",
            return_value=mock.Mock(status="ALIAS_CONFLICT"),
        ):
            renamed, errors = sheet_service._apply_player_renames(
                [{"row": 7, "pid": 1, "name": "Renamed"}]
            )

        self.assertEqual(renamed, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("kept stored name for player 1", errors[0])
        # bot.py flags the whole output as an error when it contains these substrings.
        self.assertNotIn("invalid", errors[0].lower())
        self.assertNotIn("not found", errors[0].lower())

    def test_sheet_service_imports_match_sheet_workflow_with_rename(self) -> None:
        workbook = excel_exporter.Workbook()
        ws = workbook.active
        ws["C2"] = 330
        ws["D2"] = 220
        ws.append(["MatchID", "PlayerID", "Player", "Score", "Points", "Absent", "Checkin"])
        ws.append([1, 1, "Alice Cooper", 51000, 210, "false", "true"])
        ws.append([1, 2, "Betty", 42000, 120, "true", "false"])
        local_path = Path(self.tempdir.name) / "1_Teamcup_Rivals.xlsx"
        workbook.save(local_path)

        with mock.patch.object(sheet_service, "download_match_sheet", return_value=local_path):
            outcome = sheet_service.import_match_sheet(
                self.db_path,
                1,
                workbook_reader=excel_exporter.read_match_sheet_workbook,
            )

        self.assertEqual(outcome.status, "IMPORTED")
        self.assertEqual(outcome.result.renamed, [(1, "Alice", "Alice Cooper")])
        with sqlite3.connect(self.db_path) as conn:
            name = conn.execute("SELECT name FROM players WHERE id = 1").fetchone()[0]
        self.assertEqual(name, "Alice Cooper")

    def test_sheet_service_reports_match_sheet_validation_errors(self) -> None:
        rows = [
            (4, (1, "bad", "Alice", 51000, 100, "false", "false")),
            (5, (1, 1, "Alice", 50000, 120, "false", "false")),
            (6, (1, 2, "Betty", 49000, 120, "false", "false")),
            (7, (1, 3, "Cara", 48000, 130, "false", "false")),
        ]

        result = sheet_service.validate_match_sheet_rows(
            lady_score=300,
            opponent_score=None,
            rows=rows,
            player_creator=lambda _name: None,
        )

        self.assertIn("Row 2: please fill team scores in C2 (Power Ladies) and D2 (Opponent).", result.errors)
        self.assertIn("Row 4: invalid playerID 'bad' – use a number or 'a'", result.errors)
        self.assertTrue(any("High points duplicated" in error for error in result.errors))
        self.assertTrue(any("Monotony violation" in error for error in result.errors))
        self.assertTrue(any("Team points mismatch" in error for error in result.errors))

    def test_sheet_generate_excel_uses_sanitized_paths_and_uploads(self) -> None:
        output_path = Path(self.tempdir.name) / "scores"
        match = (7, "2021-06-05", 62, "Fast Opps #1", "Team Cup!")
        players = [(1, "Alice", None, None)]

        with mock.patch.object(sheet_service, "upload_match_sheet", return_value=("remote", True)) as upload:
            result, created = sheet.generate_excel(match, players, output_path)

        self.assertTrue(created)
        self.assertIn("[7_Team_Cup_Fast_Opps_1.xlsx]", result)
        local_path, season, filename = upload.call_args.args
        self.assertEqual(local_path, output_path / "Team-Event" / "S62" / "7_Team_Cup_Fast_Opps_1.xlsx")
        self.assertEqual(season, 62)
        self.assertEqual(filename, "7_Team_Cup_Fast_Opps_1.xlsx")
        self.assertFalse(local_path.exists())
