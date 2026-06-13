from __future__ import annotations

import contextlib
import io
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hcr2.cli.app import CliApp, _should_use_legacy_dispatch
from hcr2.db import connection
from hcr2.db.migrations import apply_migrations, available_migrations
from hcr2.exporters import excel as excel_exporter
from hcr2.integrations import nextcloud
from hcr2.models.player import PlayerAbsentRow, PlayerBrief, PlayerLeaderRow, PlayerListRow, PlayerSearchRow
from hcr2.models.season import Season
from hcr2.models.vehicle import Vehicle
from hcr2.models.matchscore import MatchScoreDetail, MatchScoreListRow
from hcr2.output import matchscores as matchscore_output
from hcr2.output import stats as stats_output
from hcr2.repositories import matchscores as matchscore_repo
from hcr2.output.players import (
    format_birthday,
    print_absent_players,
    print_away_cleared,
    print_away_set,
    print_player_leaders,
    print_player_list,
    print_player_search_rows,
)
from hcr2.output.tables import render_table
from hcr2.repositories import matches as match_repo
from hcr2.repositories import players as player_repo
from hcr2.repositories import seasons as season_repo
from hcr2.repositories import stats as stats_repo
from hcr2.repositories import teamevents as teamevent_repo
from hcr2.services import matchscores as matchscore_service
from hcr2.services import players as player_service
from hcr2.services import sheets as sheet_service
from hcr2.services import stats as stats_service
from hcr2.services import vehicles as vehicle_service
from modules import donations, season, sheet, stats, vehicle


REPO_ROOT = Path(__file__).resolve().parent.parent
HCR2 = REPO_ROOT / "hcr2.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HCR2), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def run_module(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hcr2", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class CliHelpSmokeTests(unittest.TestCase):
    def assert_successful_help(self, result: subprocess.CompletedProcess[str], usage: str) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("Usage:\n", result.stdout)
        self.assertIn(f"  {usage}", result.stdout)
        self.assertIn("Commands:\n", result.stdout)
        self.assertIn("Options:\n", result.stdout)
        self.assertIn("-h, --help", result.stdout)

    def test_root_help_without_arguments(self) -> None:
        result = run_cli()
        self.assert_successful_help(result, "hcr2.py <entity> <command> [options]")
        for entity in (
            "vehicle",
            "player",
            "teamevent",
            "season",
            "match",
            "matchscore",
            "stats",
            "sheet",
            "donations",
            "version",
        ):
            self.assertIn(entity, result.stdout)

    def test_root_help_flags(self) -> None:
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                result = run_cli(flag)
                self.assert_successful_help(result, "hcr2.py <entity> <command> [options]")

    def test_package_entrypoint_matches_script_help(self) -> None:
        script_result = run_cli("--help")
        module_result = run_module("--help")
        self.assertEqual(module_result.returncode, 0, module_result.stderr)
        self.assertEqual(module_result.stdout, script_result.stdout)
        self.assertEqual(module_result.stderr, script_result.stderr)

    def test_help_command_aliases(self) -> None:
        root_result = run_cli("help")
        entity_result = run_cli("help", "player")
        self.assert_successful_help(root_result, "hcr2.py <entity> <command> [options]")
        self.assert_successful_help(entity_result, "hcr2.py player <command> [options]")

    def test_typer_completion_is_not_legacy_dispatched(self) -> None:
        self.assertFalse(_should_use_legacy_dispatch(["--show-completion", "bash"]))
        self.assertFalse(_should_use_legacy_dispatch(["--install-completion", "bash"]))

    def test_entity_help_flags(self) -> None:
        entities = {
            "vehicle": "list",
            "player": "list-active",
            "teamevent": "show --id <id>",
            "season": "list --all",
            "match": "add --opponent NAME",
            "matchscore": "list-short",
            "stats": "perf",
            "sheet": "player export",
            "donations": "under",
        }
        for entity, expected_command in entities.items():
            with self.subTest(entity=entity):
                result = run_cli(entity, "--help")
                self.assert_successful_help(result, f"hcr2.py {entity} <command> [options]")
                self.assertIn(expected_command, result.stdout)

    def test_command_help_does_not_execute_command(self) -> None:
        commands = (
            ("vehicle", "list"),
            ("player", "list"),
            ("teamevent", "list"),
            ("season", "list"),
            ("match", "list"),
            ("matchscore", "list"),
            ("stats", "perf"),
            ("sheet", "player"),
            ("donations", "list"),
        )
        for entity, command in commands:
            with self.subTest(entity=entity, command=command):
                result = run_cli(entity, command, "--help")
                self.assert_successful_help(result, f"hcr2.py {entity} <command> [options]")

    def test_version_command(self) -> None:
        result = run_cli("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^\d+\.\d+\.\d+$")

    def test_dispatcher_accepts_explicit_argv(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            CliApp().dispatch(["--help"])
        self.assertIn("hcr2.py <entity> <command> [options]", buffer.getvalue())


class TemporaryDatabaseSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "hcr2.db"

        with sqlite3.connect(self.db_path) as conn:
            pass
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

    def test_vehicle_list_reads_from_configured_database(self) -> None:
        output = self.capture_stdout(vehicle.handle_command, "list", [])
        self.assertIn("Hill Climber", output)
        self.assertIn("Rally Car", output)
        self.assertIn("hc", output)
        self.assertIn("rc", output)

    def test_vehicle_service_lists_models(self) -> None:
        vehicles = vehicle_service.list_vehicles()
        self.assertEqual([vehicle.name for vehicle in vehicles], ["Hill Climber", "Rally Car"])
        self.assertEqual([vehicle.shortname for vehicle in vehicles], ["hc", "rc"])

    def test_vehicle_service_adds_and_updates_vehicle(self) -> None:
        vehicle_service.add_vehicle("Dune Buggy", "db")
        added = [vehicle for vehicle in vehicle_service.list_vehicles() if vehicle.shortname == "db"]
        self.assertEqual(len(added), 1)

        changed = vehicle_service.edit_vehicle(added[0].id, name="Desert Buggy")
        self.assertTrue(changed)
        updated = [vehicle for vehicle in vehicle_service.list_vehicles() if vehicle.id == added[0].id]
        self.assertEqual(updated[0].name, "Desert Buggy")

    def test_vehicle_service_rejects_empty_update(self) -> None:
        self.assertFalse(vehicle_service.edit_vehicle(1))

    def test_season_list_filters_by_number(self) -> None:
        output = self.capture_stdout(season.handle_command, "list", ["--number", "2"])
        self.assertIn("Jun 21", output)
        self.assertIn("DIV1", output)
        self.assertNotIn("May 21", output)

    def test_season_repository_lists_models(self) -> None:
        seasons = season_repo.list_all()
        self.assertEqual([season.number for season in seasons], [1, 2])
        self.assertEqual([season.name for season in seasons], ["May 21", "Jun 21"])
        self.assertEqual([season.division for season in seasons], ["CC", "DIV1"])

    def test_season_repository_adds_updates_and_deletes(self) -> None:
        self.assertEqual(season_repo.get_next_season_number(), 3)

        season_repo.add_season(3, "Jul 21", "2021-07-01", "DIV2")
        self.assertTrue(season_repo.season_exists(3))
        self.assertEqual(season_repo.list_by_number(3)[0].division, "DIV2")

        season_repo.update_division(3, "DIV3")
        self.assertEqual(season_repo.list_by_number(3)[0].division, "DIV3")

        season_repo.delete_season(3)
        self.assertFalse(season_repo.season_exists(3))

    def test_match_repository_lists_and_loads_models(self) -> None:
        matches = match_repo.list_matches(season_number=2)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].event_name, "Teamcup")
        self.assertEqual(matches[0].opponent, "Rivals")

        detail = match_repo.get_match(1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.score_ladys, 123)
        self.assertEqual(detail.score_opponent, 111)

    def test_match_repository_adds_updates_and_deletes(self) -> None:
        self.assertTrue(match_repo.teamevent_exists(1))
        self.assertEqual(match_repo.latest_teamevent_id(), 1)
        self.assertEqual(match_repo.latest_match_start_between("2021-06-01", "2021-07-01"), "2021-06-05")

        match_repo.add_match(
            teamevent_id=1,
            season_number=2,
            start="2021-06-07",
            opponent="Challengers",
            score_ladys=200,
            score_opponent=199,
        )
        added = [match for match in match_repo.list_matches(season_number=2) if match.opponent == "Challengers"]
        self.assertEqual(len(added), 1)

        rowcount = match_repo.update_match(added[0].id, {"opponent": "Updated"})
        self.assertEqual(rowcount, 1)
        self.assertEqual(match_repo.get_match(added[0].id).opponent, "Updated")

        match_repo.delete_match(added[0].id)
        self.assertIsNone(match_repo.get_match(added[0].id))

    def test_matchscore_repository_lists_and_loads_models(self) -> None:
        rows = matchscore_repo.query_rows(None, None, force_current_when_all=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, 1)
        self.assertEqual(rows[0].player_name, "Alice")
        self.assertEqual(rows[0].score, 50000)

        detail = matchscore_repo.fetch_score_by_id(1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.match_id, 1)
        self.assertEqual(detail.opponent, "Rivals")

        unique = matchscore_repo.fetch_by_match_player(1, 1)
        self.assertIsNotNone(unique)
        self.assertEqual(unique.points, 200)

    def test_matchscore_repository_mutates_scores(self) -> None:
        self.assertEqual(matchscore_repo.get_match_start(1), "2021-06-05")
        self.assertEqual(matchscore_repo.get_player_away_window(1), (None, None))
        self.assertEqual(matchscore_repo.get_match_result(1), (123, 111))
        self.assertEqual([player.name for player in matchscore_repo.find_players("ali")], ["Alice"])

        self.assertEqual(matchscore_repo.update_score_fields(1, {"score": 51000}), 1)
        self.assertEqual(matchscore_repo.fetch_score_by_id(1).score, 51000)

        matchscore_repo.insert_score(match_id=1, player_id=2, score=30000, points=100, absent=0, checkin=0)
        inserted = matchscore_repo.fetch_by_match_player(1, 2)
        self.assertIsNotNone(inserted)
        self.assertEqual(inserted.score, 30000)

        self.assertEqual(matchscore_repo.delete_score(inserted.id), 1)
        self.assertIsNone(matchscore_repo.fetch_by_match_player(1, 2))

    def test_matchscore_service_adds_updates_and_deletes_scores(self) -> None:
        added = matchscore_service.add_score(
            match_id=1,
            player_input="Betty",
            score=30000,
            points=100,
            checkin_override=1,
        )
        self.assertEqual(added.status, "CHANGED")

        inserted = matchscore_repo.fetch_by_match_player(1, 2)
        self.assertIsNotNone(inserted)
        self.assertEqual(inserted.score, 30000)
        self.assertEqual(inserted.checkin, 1)

        unchanged = matchscore_service.add_score(
            match_id=1,
            player_input="2",
            score=30000,
            points=100,
            checkin_override=1,
        )
        self.assertEqual(unchanged.status, "UNCHANGED")

        changed = matchscore_service.add_score(
            match_id=1,
            player_input="2",
            score=31000,
            points=101,
            checkin_override=1,
        )
        self.assertEqual(changed.status, "CHANGED")

        deleted = matchscore_service.delete_score(inserted.id)
        self.assertIsNotNone(deleted.row)
        self.assertEqual(deleted.row.player_name, "Betty")
        self.assertIsNone(matchscore_repo.fetch_by_match_player(1, 2))

    def test_matchscore_service_rejects_ambiguous_player_name_and_missing_delete(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO players (id, name, alias, garage_power, active, birthday, team, discord_name, is_leader)
                VALUES (3, 'Alicia', 'ali2', 4100, 1, NULL, 'PLTE', NULL, 0)
                """
            )

        ambiguous = matchscore_service.add_score(
            match_id=1,
            player_input="ali",
            score=30000,
            points=100,
        )
        self.assertEqual(ambiguous.status, "PLAYER_AMBIGUOUS")
        self.assertIsNotNone(ambiguous.player_resolution)
        self.assertEqual([player.name for player in ambiguous.player_resolution.matches], ["Alice", "Alicia"])

        missing_delete = matchscore_service.delete_score(999)
        self.assertIsNone(missing_delete.row)

    def test_matchscore_service_lists_latest_match_by_default(self) -> None:
        match_repo.add_match(
            teamevent_id=1,
            season_number=2,
            start="2021-06-07",
            opponent="Challengers",
            score_ladys=200,
            score_opponent=199,
        )
        second_match_id = [match.id for match in match_repo.list_matches(season_number=2) if match.opponent == "Challengers"][0]
        matchscore_repo.insert_score(match_id=second_match_id, player_id=2, score=30000, points=100, absent=0, checkin=0)

        latest_only = matchscore_service.list_scores(show_all=False, season_filter=None, match_filter=None)
        self.assertEqual([row.match_id for row in latest_only.rows], [second_match_id])

        all_current = matchscore_service.list_scores(show_all=True, season_filter=None, match_filter=None)
        self.assertEqual({row.match_id for row in all_current.rows}, {1, second_match_id})

    def test_matchscore_service_filters_by_season_and_match(self) -> None:
        match_repo.add_match(
            teamevent_id=1,
            season_number=1,
            start="2021-05-07",
            opponent="Old Rivals",
            score_ladys=100,
            score_opponent=90,
        )
        old_match_id = [match.id for match in match_repo.list_matches(season_number=1) if match.opponent == "Old Rivals"][0]
        matchscore_repo.insert_score(match_id=old_match_id, player_id=2, score=25000, points=80, absent=0, checkin=0)

        season_one = matchscore_service.list_scores(show_all=True, season_filter="1", match_filter=None)
        self.assertEqual([row.match_id for row in season_one.rows], [old_match_id])

        season_two = matchscore_service.list_scores(show_all=True, season_filter="S2", match_filter=None)
        self.assertEqual([row.match_id for row in season_two.rows], [1])

        by_match = matchscore_service.list_scores(show_all=False, season_filter=None, match_filter=old_match_id)
        self.assertEqual([row.match_id for row in by_match.rows], [old_match_id])

    def test_matchscore_service_edits_score_and_rejects_clashing_player(self) -> None:
        matchscore_repo.insert_score(match_id=1, player_id=2, score=30000, points=100, absent=0, checkin=0)

        updated = matchscore_service.edit_score(1, score=51000, points=201, toggle_checkin=True)
        self.assertEqual(updated.status, "UPDATED")
        self.assertIsNotNone(updated.row)
        self.assertEqual(updated.row.score, 51000)
        self.assertEqual(updated.row.points, 201)
        self.assertEqual(updated.row.checkin, 0)

        clash = matchscore_service.edit_score(1, player_id=2)
        self.assertEqual(clash.status, "PLAYER_CLASH")
        self.assertEqual(clash.player_id, 2)

    def test_matchscore_service_validates_edit_ranges_and_recomputes_absent(self) -> None:
        self.assertEqual(matchscore_service.edit_score(1, score=75001).status, "SCORE_OUT_OF_RANGE")
        self.assertEqual(matchscore_service.edit_score(1, points=301).status, "POINTS_OUT_OF_RANGE")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE players
                SET away_from = '2021-06-01', away_until = '2021-06-10'
                WHERE id = 1
                """
            )

        updated = matchscore_service.edit_score(1, score=51000)
        self.assertEqual(updated.status, "UPDATED")
        refreshed = matchscore_repo.fetch_by_match_player(1, 1)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.absent, 1)

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

    def test_sheet_service_builds_paths_and_parses_k_amounts(self) -> None:
        filename = sheet_service.match_sheet_filename(7, "Team Cup!", "Fast Opps #1")
        self.assertEqual(filename, "7_Team_Cup_Fast_Opps_1.xlsx")
        self.assertEqual(
            sheet_service.match_sheet_remote_path_for_filename(62, filename).as_posix(),
            "Power-Ladys-Scores/S62/7_Team_Cup_Fast_Opps_1.xlsx",
        )
        self.assertEqual(sheet_service.scores_web_url(62), "https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path=/Scores/S62")
        self.assertEqual(sheet_service.to_k(12500), 12.5)
        self.assertEqual(sheet_service.parse_k_amount("12,5k"), 12500)
        self.assertEqual(sheet_service.parse_k_amount(7), 7000)
        self.assertIsNone(sheet_service.parse_k_amount("-1"))

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

        with mock.patch.object(sheet, "upload_to_nextcloud", return_value=("remote", True)) as upload:
            result, created = sheet.generate_excel(match, players, output_path)

        self.assertTrue(created)
        self.assertIn("[7_Team_Cup_Fast_Opps_1.xlsx]", result)
        local_path, remote_path = upload.call_args.args
        self.assertEqual(local_path, output_path / "S62" / "7_Team_Cup_Fast_Opps_1.xlsx")
        self.assertEqual(remote_path.as_posix(), "Power-Ladys-Scores/S62/7_Team_Cup_Fast_Opps_1.xlsx")
        self.assertFalse(local_path.exists())

    def test_teamevent_repository_lists_and_loads_models(self) -> None:
        events = teamevent_repo.list_latest()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "Teamcup")
        self.assertEqual(teamevent_repo.latest_iso_week(), (2021, 21))

        detail = teamevent_repo.get_teamevent(1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.tracks, 4)

    def test_teamevent_repository_adds_updates_vehicles_and_deletes(self) -> None:
        self.assertEqual(teamevent_repo.resolve_vehicle_id("hc"), 1)
        self.assertEqual(teamevent_repo.resolve_vehicle_id("Rally Car", allow_name_lookup=True), 2)

        teamevent_id, invalid = teamevent_repo.add_teamevent(
            name="New Cup",
            iso_year=2021,
            iso_week=22,
            tracks=5,
            max_score_per_track=12000,
            vehicle_ids=[1, 2],
        )
        self.assertIsNotNone(teamevent_id)
        self.assertEqual(invalid, [])
        self.assertEqual([vehicle.id for vehicle in teamevent_repo.list_event_vehicles(teamevent_id)], [1, 2])

        rowcount = teamevent_repo.update_teamevent(teamevent_id, {"name": "Updated Cup"})
        self.assertEqual(rowcount, 1)
        self.assertEqual(teamevent_repo.get_teamevent(teamevent_id).name, "Updated Cup")

        warnings = teamevent_repo.replace_event_vehicles(teamevent_id, [2])
        self.assertEqual(warnings, [])
        self.assertEqual([vehicle.id for vehicle in teamevent_repo.list_event_vehicles(teamevent_id)], [2])

        teamevent_repo.clear_event_vehicles(teamevent_id)
        self.assertEqual(teamevent_repo.list_event_vehicles(teamevent_id), [])

        teamevent_repo.delete_teamevent(teamevent_id)
        self.assertIsNone(teamevent_repo.get_teamevent(teamevent_id))

    def test_player_repository_lists_and_loads_models(self) -> None:
        players = player_repo.list_players(sort_by="gp")
        self.assertEqual([player.name for player in players], ["Alice", "Betty"])
        self.assertEqual(player_repo.count_active_players(), 1)

        active_plte = player_repo.list_players(active_only=True, team_filter="PLTE")
        self.assertEqual([player.name for player in active_plte], ["Alice"])

        detail = player_repo.get_player_detail(1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "Alice")
        self.assertEqual(detail.match_count, 1)
        self.assertEqual(detail.first_match, "2021-06-05")
        self.assertEqual(detail.last_match, "2021-06-05")

    def test_player_repository_updates_active_and_deletes(self) -> None:
        player_repo.set_active(2, True)
        self.assertEqual(player_repo.count_active_players(), 2)

        player_repo.set_active(2, False)
        self.assertEqual(player_repo.get_player_detail(2).active, 0)

        player_repo.delete_player(2)
        self.assertIsNone(player_repo.get_player_detail(2))

    def test_player_repository_adds_player_and_checks_aliases(self) -> None:
        new_id = player_repo.add_player(
            name="Clara",
            alias="clara",
            garage_power=3000,
            active=True,
            birthday="02-14",
            team="PLTE",
            discord_name="clara#1",
        )
        self.assertTrue(player_repo.alias_exists("clara", team_scope="PLTE"))
        detail = player_repo.get_player_detail(new_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "Clara")
        self.assertEqual(detail.birthday, "02-14")

        self.assertEqual(player_repo.update_player_fields(new_id, {"garage_power": 3500}), 1)
        self.assertEqual(player_repo.get_player_detail(new_id).garage_power, 3500)

    def test_player_repository_lists_birthdays(self) -> None:
        self.assertEqual(player_repo.get_birthday_player_ids("01-15"), [1])
        birthdays = player_repo.list_birthday_players(active_only=True)
        self.assertEqual([row.name for row in birthdays], ["Alice"])

    def test_player_repository_searches_and_lists_leaders(self) -> None:
        self.assertEqual([row.name for row in player_repo.search_players_like("ali")], ["Alice"])
        self.assertEqual(player_repo.resolve_player_id_exact("alice"), [1])
        self.assertEqual([row.name for row in player_repo.list_leaders()], ["Alice"])

    def test_player_service_lists_detail_and_mutates_basis(self) -> None:
        result = player_service.list_players(active_only=True, team_filter="PLTE")
        self.assertEqual(result.active_count, 1)
        self.assertEqual([player.name for player in result.rows], ["Alice"])

        detail = player_service.get_player_detail(1)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "Alice")

        player_service.activate_player(2)
        self.assertEqual(player_service.list_players().active_count, 2)

        player_service.deactivate_player(2)
        self.assertEqual(player_service.get_player_detail(2).active, 0)

        player_service.delete_player(2)
        self.assertIsNone(player_service.get_player_detail(2))

    def test_player_service_adds_player_with_generated_alias(self) -> None:
        result = player_service.add_player(name="Clara Driver", team="PLTE", gp=3000, active=True)
        self.assertEqual(result.status, "ADDED")
        self.assertEqual(result.alias, "claradriver1")
        self.assertTrue(result.alias_generated)

        detail = player_service.get_player_detail(result.player_id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.name, "Clara Driver")
        self.assertEqual(detail.alias, "claradriver1")

    def test_player_service_rejects_plte_alias_conflict(self) -> None:
        result = player_service.add_player(name="Alice Clone", alias="alice", team="PLTE")
        self.assertEqual(result.status, "ALIAS_CONFLICT")

    def test_player_service_parses_birthday_and_validates_team(self) -> None:
        self.assertEqual(player_service.parse_birthday("15.01."), "01-15")
        self.assertIsNone(player_service.parse_birthday("2021-01-15"))
        self.assertTrue(player_service.is_valid_team("PLTE"))
        self.assertFalse(player_service.is_valid_team("PL10"))

    def test_player_service_edits_player_fields(self) -> None:
        result = player_service.edit_player(
            2,
            name="Betty Updated",
            gp=4500,
            active=True,
            birthday="02-14",
            team="PL1",
            discord_name="betty#2",
            leader=True,
        )
        self.assertEqual(result.status, "UPDATED")

        detail = player_service.get_player_detail(2)
        self.assertEqual(detail.name, "Betty Updated")
        self.assertEqual(detail.garage_power, 4500)
        self.assertEqual(detail.active, 1)
        self.assertEqual(detail.birthday, "02-14")
        self.assertEqual(detail.discord_name, "betty#2")
        self.assertEqual(detail.is_leader, 1)

    def test_player_service_edit_reports_noop_and_alias_conflict(self) -> None:
        self.assertEqual(player_service.edit_player(2).status, "NOTHING_TO_UPDATE")

        player_service.add_player(name="Ally", alias="ally", team="PLTE")
        conflict = player_service.edit_player(2, team="PLTE", alias="all")
        self.assertEqual(conflict.status, "ALIAS_CONFLICT")
        self.assertEqual(conflict.alias, "all")
        self.assertEqual(conflict.conflict_alias, "ally")

    def test_player_service_lists_birthdays(self) -> None:
        with mock.patch.object(player_service, "today_mm_dd", return_value="01-15"):
            self.assertEqual(player_service.birthday_ids_for_today(), [1])

        result = player_service.list_birthdays(active_only=True, num=1)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0][1].name, "Alice")

    def test_player_service_searches_and_lists_leaders(self) -> None:
        self.assertEqual([row.name for row in player_service.search_players("ali")], ["Alice"])
        self.assertEqual(player_service.resolve_player_id_exact("alice"), 1)
        self.assertEqual(player_service.resolve_player_id_fuzzy("ali").player_id, 1)
        self.assertEqual([row.name for row in player_service.list_leaders()], ["Alice"])

    def test_player_service_sets_and_clears_away(self) -> None:
        self.assertEqual(player_service.parse_weeks_token("2w"), 14)
        set_result = player_service.set_away_for_player(1, days=7)
        self.assertEqual(set_result.status, "SET")
        self.assertIsNotNone(set_result.brief)

        detail = player_service.get_player_detail(1)
        self.assertIsNotNone(detail.away_from)
        self.assertIsNotNone(detail.away_until)

        clear_result = player_service.clear_away_for_player(1)
        self.assertEqual(clear_result.status, "CLEARED")
        self.assertIsNotNone(clear_result.brief)
        self.assertIsNone(player_service.get_player_detail(1).away_until)

    def test_stats_score_points_rank_and_perf_outputs(self) -> None:
        score_output = self.capture_stdout(stats.handle_command, "score", ["2"])
        self.assertIn("📊Score Season 2 (Jun 21) DIV: DIV1", score_output)
        self.assertIn("Alice", score_output)
        self.assertIn("50000", score_output)

        points_output = self.capture_stdout(stats.handle_command, "points", ["2"])
        self.assertIn("📊Points Season 2 (Jun 21) DIV: DIV1", points_output)
        self.assertIn("Alice", points_output)
        self.assertIn("200", points_output)

        rank_output = self.capture_stdout(stats.handle_command, "rank", ["2"])
        self.assertIn("Lady", rank_output)
        self.assertIn("Alice", rank_output)

        perf_output = self.capture_stdout(stats.handle_command, "perf", ["2"])
        self.assertIn("📈Performance Season 2 (Jun 21) DIV: DIV1", perf_output)
        self.assertIn("ℹ️ Required matches: 1/1 (20%)", perf_output)
        self.assertIn("Alice", perf_output)

    def test_stats_repository_loads_common_rows(self) -> None:
        self.assertEqual(stats_repo.get_season_meta(2), ("Jun 21", "DIV1"))
        self.assertEqual(stats_repo.get_min_required_matches(2), (1, 1))
        self.assertEqual([row[1] for row in stats_repo.fetch_season_rows(2)], ["Alice"])
        self.assertEqual(stats_repo.list_active_plte_players(), [(1, "Alice")])
        self.assertEqual(stats_repo.list_active_plte_player_ids(), {1})
        self.assertEqual(stats_repo.fetch_unexcused_absences(2), [])
        self.assertEqual(stats_repo.resolve_teamevent_by_offset(0), 1)
        self.assertEqual(stats_repo.get_teamevent_meta(1)[0], "Teamcup")
        self.assertEqual([row[1] for row in stats_repo.fetch_teamevent_rows(1)], ["Alice"])
        self.assertEqual(stats_repo.fetch_avg_score_last_seasons(2), [(2, 50000.0)])
        self.assertEqual([row[0] for row in stats_repo.fetch_birthday_plot_rows()], ["Alice"])
        self.assertEqual(stats_repo.fetch_season_matches(2), [(1, "2021-06-05")])
        self.assertEqual(stats_repo.fetch_player_meta_for_ids(1, 2)[1][0], "Alice")
        self.assertEqual(stats_repo.fetch_matchscores_for_matches_players([1], 1, 2)[0][0], 1)
        self.assertEqual(stats_repo.get_player_stats_meta(1)[0], "Alice")
        self.assertEqual(stats_repo.count_player_matchscores(1), 1)
        self.assertEqual(stats_repo.count_player_unexcused_absences(1), 0)
        self.assertEqual(stats_repo.fetch_player_last_matches(1, 1)[0][3], "Teamcup")
        self.assertEqual(stats_repo.fetch_player_overall_matches(1)[0][0], 1)
        self.assertEqual(stats_repo.fetch_match_rows_for_medians([1])[0][0], 1)
        self.assertIsNone(stats_repo.get_latest_donation_date())

    def test_stats_service_calculates_delta_entries(self) -> None:
        self.assertFalse(stats_service.is_absent(50000, 200, 1))
        self.assertTrue(stats_service.is_absent(0, 0, 1))
        self.assertTrue(stats_service.is_active_plte(1, "PLTE"))

        scores_by_match = {}
        stats_service.append_scored_match(scores_by_match, 1, 1, "Alice", 50000, 4)
        stats_service.append_scored_match(scores_by_match, 1, 2, "Betty", 40000, 4)
        player_scores, labels, counts = stats_service.calculate_match_deltas(scores_by_match)
        entries = stats_service.build_delta_entries(player_scores, labels, counts)
        self.assertEqual(stats_service.sorted_delta_entries(entries)[0], ("Alice", 5000, 1))
        self.assertEqual(stats_service.trend_to_score(stats_service.linreg_slope([0.0, 200.0])), 3)
        self.assertEqual(stats_service.trend_label(-1), "↘-1")
        self.assertTrue(stats_service.is_unexcused_absence(0, 0, 0))
        medians = stats_service.calculate_match_medians(
            [
                (1, 50000, 200, 0, "PLTE", 4),
                (1, 40000, 150, 0, "PLTE", 4),
            ]
        )
        self.assertEqual(medians[1], 45000)

    def test_stats_service_summarizes_player_detail_and_donations(self) -> None:
        last_matches = [
            (2, "2021-06-12", 2, "Cup 2", 4, 52000, 210, 0),
            (1, "2021-06-05", 2, "Cup 1", 4, 0, 0, 0),
        ]
        overall_matches = [
            (1, "2021-06-05", 4, 0, 0, 0),
            (2, "2021-06-12", 4, 52000, 210, 0),
        ]
        summary = stats_service.summarize_player_stats(
            last_matches,
            overall_matches,
            {2: 50000},
            total_unexcused_overall=1,
        )

        self.assertEqual(summary.last_counted, 2)
        self.assertEqual(summary.last_unexcused, 1)
        self.assertEqual(summary.last_avg_score, 26000)
        self.assertEqual(summary.last_perf_by_match, {2: 2000, 1: None})
        self.assertEqual(summary.overall_unexcused, 1)

        donations = stats_service.summarize_player_donations(
            start_date="2025-11-01",
            cutoff_date="2025-11-15",
            matches=2,
            total=900,
        )
        self.assertEqual(donations.expected, 1200)
        self.assertEqual(donations.index, 75.0)

    def test_stats_output_prints_player_detail(self) -> None:
        summary = stats_service.PlayerStatsSummary(
            last_counted=1,
            last_unexcused=0,
            last_avg_score=50000,
            last_avg_points=200,
            last_avg_perf=5000,
            last_trend=0,
            overall_counted=1,
            overall_unexcused=0,
            overall_avg_score=50000,
            overall_avg_points=200,
            overall_avg_perf=5000,
            overall_trend=0,
            last_perf_by_match={1: 5000},
        )
        donations = stats_service.PlayerDonationSummary(
            start_date="2025-11-01",
            cutoff_date="2025-11-15",
            matches=1,
            expected=600,
            total=600,
            index=100.0,
        )

        output = self.capture_stdout(
            lambda: stats_output.print_player_detail(
                player_id=1,
                player_meta=("Alice", "A", "PLTE", 1, 1234),
                last_n=1,
                last_matches=[(1, "2021-06-05", 2, "Teamcup", 4, 50000, 200, 0)],
                summary=summary,
                total_matches_overall=1,
                donations=donations,
            )
        )
        self.assertIn("👤 1: Alice A (GP 1234, PLTE, act 1)", output)
        self.assertIn("Teamcup", output)
        self.assertIn("Avg perf", output)
        self.assertIn("📦 Donations since 2025-11-01 → 2025-11-15", output)

    def test_stats_te_absent_and_player_outputs(self) -> None:
        te_output = self.capture_stdout(stats.handle_command, "te", ["1"])
        self.assertIn("📊 Performance Team Event 1: Teamcup (2021-W21)", te_output)
        self.assertIn("Alice", te_output)

        absent_output = self.capture_stdout(stats.handle_command, "absent", ["2"])
        self.assertIn("🚫 Unexcused absences", absent_output)
        self.assertIn("✅ No unexcused absences.", absent_output)

        player_output = self.capture_stdout(stats.handle_command, "player", ["1", "1"])
        self.assertIn("👤 1: Alice", player_output)
        self.assertIn("Teamcup", player_output)
        self.assertIn("📦 Donations since 2025-11-01", player_output)

    def test_stats_alias_scatter_bdayplot_and_battle_outputs(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO players (id, name, alias, garage_power, active, birthday, team, discord_name, is_leader, emoji)
                VALUES (3, 'Clara', 'clara', 4500, 1, '02-14', 'PLTE', 'clara#1', 0, 'C')
                """
            )
            conn.execute(
                """
                INSERT INTO matchscore (id, match_id, player_id, score, points, absent, checkin)
                VALUES (3, 1, 3, 40000, 150, 0, 1)
                """
            )

        with mock.patch.object(stats, "find_current_season", return_value=2):
            alias_output = self.capture_stdout(stats.handle_command, "alias", [])
        self.assertIn("alice", alias_output)
        self.assertIn("clara", alias_output)

        scatter_output = self.capture_stdout(stats.handle_command, "scatter", ["2"])
        self.assertIn("Avg score per season", scatter_output)
        self.assertIn("S2", scatter_output)

        bday_output = self.capture_stdout(stats.handle_command, "bdayplot", [])
        self.assertIn("Power Ladies Birthday Map", bday_output)
        self.assertIn("C", bday_output)

        battle_output = self.capture_stdout(stats.handle_command, "battle", ["1", "3", "2"])
        self.assertIn("Battle Alice", battle_output)
        self.assertIn("Clara", battle_output)
        self.assertIn("Season 2", battle_output)


class OutputFormattingTests(unittest.TestCase):
    def test_render_table_joins_headers_rule_and_rows(self) -> None:
        table = render_table(
            headers=["ID", "Name"],
            rows=[["1.", "Hill Climber"], ["2.", "Rally Car"]],
            width=12,
        )
        self.assertEqual(
            table,
            "ID Name\n------------\n1. Hill Climber\n2. Rally Car",
        )

    def test_domain_models_are_plain_values(self) -> None:
        self.assertEqual(Vehicle(1, "Hill Climber", "hc").shortname, "hc")
        self.assertEqual(Season(1, "May 21", "2021-05-01", "CC").division, "CC")

    def test_player_output_formats_birthday(self) -> None:
        self.assertEqual(format_birthday("01-15"), "15.01.")
        self.assertEqual(format_birthday(None), "-")

    def test_player_output_prints_standard_list_footer_once(self) -> None:
        result = player_service.PlayerListResult(
            rows=[
                PlayerListRow(
                    id=1,
                    name="Alice",
                    alias="alice",
                    garage_power=5000,
                    active=1,
                    created_at="2021-01-01 00:00:00",
                    birthday="01-15",
                    team="PLTE",
                    discord_name="alice#1",
                    is_leader=1,
                    active_modified=None,
                    away_until=None,
                )
            ],
            active_count=1,
        )
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_player_list(result)
        self.assertEqual(buffer.getvalue().count("Active players:"), 1)

    def test_player_output_prints_search_rows(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_player_search_rows(
                [PlayerSearchRow(id=1, name="Alice", alias="alice", garage_power=5000, active=1, discord_name="alice#1")]
            )
        self.assertIn("ID   NAME", buffer.getvalue())
        self.assertIn("1    Alice", buffer.getvalue())
        self.assertIn("alice#1", buffer.getvalue())

    def test_player_output_prints_leaders(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_player_leaders([PlayerLeaderRow(id=1, name="Alice", discord_name="alice#1")])
        self.assertIn("ID   Name", buffer.getvalue())
        self.assertIn("👑 Leaders: 1", buffer.getvalue())

    def test_player_output_prints_absent_rows(self) -> None:
        buffer = io.StringIO()
        result = player_service.PlayerAbsentListResult(
            rows=[
                (
                    7,
                    PlayerAbsentRow(
                        id=1,
                        name="Alice",
                        team="PLTE",
                        away_until="2021-06-12 00:00:00",
                    ),
                )
            ]
        )
        with contextlib.redirect_stdout(buffer):
            print_absent_players(result)
        self.assertIn("🛫 Absent Ladies", buffer.getvalue())
        self.assertIn("Alice", buffer.getvalue())
        self.assertIn("Count: 1", buffer.getvalue())

    def test_player_output_prints_away_set_and_clear(self) -> None:
        brief = PlayerBrief(id=1, name="Alice", alias="alice", discord_name="alice#1")
        set_result = player_service.AwaySetResult(
            status="SET",
            player_id=1,
            brief=brief,
            away_from="2021-06-05 00:00:00",
            away_until="2021-06-12 00:00:00",
        )
        clear_result = player_service.AwayClearResult(status="CLEARED", player_id=1, brief=brief)

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_away_set(set_result)
            print_away_cleared(clear_result)
        output = buffer.getvalue()
        self.assertIn("✅ Away set", output)
        self.assertIn("From → Until : 2021-06-05 00:00:00  →  2021-06-12 00:00:00", output)
        self.assertIn("✅ Back: absence cleared", output)

    def test_stats_output_prints_perf_table(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats_output.print_perf_table([("Alice", 5000, 1)])
        self.assertIn("Lady", buffer.getvalue())
        self.assertIn("Alice", buffer.getvalue())
        self.assertIn("5.0k", buffer.getvalue())

    def test_stats_output_prints_sum_metric_table(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats_output.print_sum_metric_table([("Alice", 50000, 1), ("Betty", None, 0)], metric="score")
        output = buffer.getvalue()
        self.assertIn("Score", output)
        self.assertIn("Alice", output)
        self.assertIn("50000", output)
        self.assertIn("-", output)

    def test_excel_exporter_builds_players_workbook(self) -> None:
        wb = excel_exporter.build_players_workbook(["id", "name", "garage_power"], [(1, "Alice", 5000)])
        ws = wb.active
        self.assertEqual(ws.title, "players")
        self.assertEqual([cell.value for cell in ws[1]], ["id", "name", "garage_power"])
        self.assertEqual([cell.value for cell in ws[2]], [1, "Alice", 5000])
        self.assertTrue(ws["A1"].font.bold)

    def test_excel_exporter_builds_donations_workbook(self) -> None:
        wb = excel_exporter.build_donations_workbook([(1, "Alice", 12500)], "2026-06-13")
        ws = wb.active
        self.assertEqual(ws.title, "donations")
        self.assertEqual(ws["A1"].value, "Date:")
        self.assertEqual(ws["A2"].value, "2026-06-13")
        self.assertEqual(
            [ws["A3"].value, ws["B3"].value, ws["C3"].value, ws["D3"].value],
            ["id", "name", "donation (k)", "previous (k)"],
        )
        self.assertEqual([ws["A4"].value, ws["B4"].value, ws["C4"].value, ws["D4"].value], [1, "Alice", "", 12.5])

    def test_excel_exporter_reads_players_workbook(self) -> None:
        wb = excel_exporter.build_players_workbook(
            ["id", "name", "garage_power"],
            [(1, "Alice", 5000), (2, "Betty", 4000)],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "players.xlsx"
            wb.save(path)

            header, rows = excel_exporter.read_players_workbook(path)

        self.assertEqual(header, ["id", "name", "garage_power"])
        self.assertEqual(rows[0]["id"], 1)
        self.assertEqual(rows[1]["name"], "Betty")

    def test_excel_exporter_reads_donations_workbook_entries(self) -> None:
        wb = excel_exporter.build_donations_workbook([(1, "Alice", 12500), (2, "Betty", 0)], "2026-06-13")
        ws = wb.active
        ws["C4"] = "13,5k"
        ws["C5"] = ""
        ws.append(["bad", "Invalid", "7"])
        ws.append([3, "Cara", "nope"])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "donations.xlsx"
            wb.save(path)

            date_str, entries, errors = excel_exporter.read_donations_workbook(path)

        self.assertEqual(date_str, "2026-06-13")
        self.assertEqual(entries, [(1, 13500)])
        self.assertEqual(errors, 2)

    def test_excel_exporter_reads_match_sheet_workbook(self) -> None:
        wb = excel_exporter.Workbook()
        ws = wb.active
        ws["C2"] = 330
        ws["D2"] = "220"
        ws.append(["MatchID", "PlayerID", "Player", "Score", "Points", "Absent", "Checkin"])
        ws.append([1, 1, "Alice", 51000, 210, "false", "true"])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "match.xlsx"
            wb.save(path)

            lady_score, opponent_score, rows = excel_exporter.read_match_sheet_workbook(path)

        self.assertEqual(lady_score, 330)
        self.assertEqual(opponent_score, 220)
        self.assertEqual(rows, [(4, (1, 1, "Alice", 51000, 210, "false", "true"))])

    def test_stats_output_prints_absent_stats(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats_output.print_absent_stats(2, [])
        output = buffer.getvalue()
        self.assertIn("🚫 Unexcused absences", output)
        self.assertIn("✅ No unexcused absences.", output)

    def test_stats_output_prints_battle_plot(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats_output.print_battle_plot(
                name1="Alice",
                emoji1="A",
                name2="Betty",
                emoji2="B",
                season_number=2,
                match_ids=[1],
                scores={(1, 1): 50000, (1, 2): 40000},
                player1_id=1,
                player2_id=2,
                height=5,
                col_width=2,
            )
        output = buffer.getvalue()
        self.assertIn("Battle Alice A vs Betty B (Season 2)", output)
        self.assertIn("└", output)
        self.assertIn("1", output)

    def test_stats_output_builds_scatter_and_birthday_plots(self) -> None:
        scatter = stats_output.scatter_fixed([(2, 50000.0)], height=4, width=20, x_labels=2)
        self.assertIn("Avg score per season", scatter)
        self.assertIn("S2", scatter)

        birthday = stats_output.birthday_plot([("Clara", "02-14", "C")])
        self.assertIn("Power Ladies Birthday Map", birthday)
        self.assertIn("C", birthday)

    def test_matchscore_output_prints_short_group(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            matchscore_output.print_grouped_rows(
                [_matchscore_row()],
                show_all=False,
                match_filter=None,
                short=True,
                match_result_loader=lambda match_id: (123, 111),
            )
        self.assertEqual(
            buffer.getvalue(),
            "Match 1 – Rivals | 2021-06-05\n"
            "ID     Player           Score Pts\n"
            "----------------------------------\n"
            "1      Alice            50000 200\n\n",
        )

    def test_matchscore_output_prints_detail_group_with_result(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            matchscore_output.print_grouped_rows(
                [_matchscore_row()],
                show_all=False,
                match_filter=None,
                short=False,
                match_result_loader=lambda match_id: (123, 111),
            )
        output = buffer.getvalue()
        self.assertIn("📊 Match 1 – Rivals | 2021-06-05 | Season Jun 21", output)
        self.assertIn("Result: 123 : 111 🏆", output)
        self.assertIn("ID     PID    Player           Score Pts", output)
        self.assertIn("1      1      Alice            50000 200", output)

    def test_matchscore_output_prints_delete_result(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            matchscore_output.print_deleted_score(_matchscore_detail())
        self.assertEqual(
            buffer.getvalue(),
            "OK DELETED:\n"
            "ID=1 match=1 date=2021-06-05 opp=Rivals player=Alice score=50000 points=200 absent=0 checkin=1\n",
        )

    def test_matchscore_output_prints_edit_result(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            matchscore_output.print_updated_score(_matchscore_detail())
        output = buffer.getvalue()
        self.assertIn("OK UPDATED:", output)
        self.assertIn("Match 1 – Rivals | 2021-06-05", output)
        self.assertIn("ID     Player           Score Pts Abs Cin", output)
        self.assertIn("1      Alice            50000 200   0   1", output)


class NextcloudIntegrationTests(unittest.TestCase):
    def test_match_sheet_remote_path(self) -> None:
        self.assertEqual(
            nextcloud.match_sheet_remote_path(62, "12_Event_Opponent.xlsx").as_posix(),
            "Power-Ladys-Scores/S62/12_Event_Opponent.xlsx",
        )

    def test_remote_url_normalizes_leading_slash(self) -> None:
        with mock.patch.object(nextcloud, "NEXTCLOUD_AUTH", ("user", "secret")):
            self.assertEqual(
                nextcloud.remote_url("/Power-Ladys-Scores/Ladys.xlsx"),
                "http://192.168.178.101:8080/remote.php/dav/files/user/Power-Ladys-Scores/Ladys.xlsx",
            )


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


def _matchscore_row() -> MatchScoreListRow:
    return MatchScoreListRow(
        id=1,
        match_id=1,
        match_start="2021-06-05",
        opponent="Rivals",
        season_name="Jun 21",
        season_division="DIV1",
        player_name="Alice",
        player_id=1,
        score=50000,
        points=200,
        absent=0,
        checkin=1,
    )


def _matchscore_detail() -> MatchScoreDetail:
    return MatchScoreDetail(
        id=1,
        match_id=1,
        match_start="2021-06-05",
        opponent="Rivals",
        season_name="Jun 21",
        season_division="DIV1",
        player_name="Alice",
        score=50000,
        points=200,
        absent=0,
        checkin=1,
    )


if __name__ == "__main__":
    unittest.main()
