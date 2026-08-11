from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from hcr2.exporters import excel as excel_exporter
from hcr2.models.matchscore import MatchScoreDetail, MatchScoreListRow, PlayerLookup
from hcr2.models.player import PlayerAbsentRow, PlayerBirthdayRow, PlayerBrief, PlayerLeaderRow, PlayerListRow, PlayerSearchRow
from hcr2.models.season import Season
from hcr2.models.vehicle import Vehicle
from hcr2.output import donations as donation_output
from hcr2.output import matchscores as matchscore_output
from hcr2.output import sheets as sheet_output
from hcr2.output import stats as stats_output
from hcr2.output.players import (
    format_birthday,
    print_absent_players,
    print_active_requires_bool,
    print_add_player_result,
    print_away_cleared,
    print_away_selector_required,
    print_away_set,
    print_birthday_ids,
    print_birthday_list,
    print_edit_player_result,
    print_explicit_player_resolution_result,
    print_gp_requires_integer,
    print_grep_result,
    print_invalid_birthday_format,
    print_invalid_id,
    print_invalid_team_name,
    print_invalid_team_value,
    print_leader_requires_bool,
    print_name_required,
    print_no_matching_player,
    print_num_requires_integer,
    print_player_activated,
    print_player_deactivated,
    print_player_deleted,
    print_player_id_not_found,
    print_player_leaders,
    print_player_list,
    print_player_resolution_result,
    print_player_search_rows,
    print_single_selector_required,
    print_value_error,
)
from hcr2.output.tables import render_table
from hcr2.services import matchscores as matchscore_service
from hcr2.services import players as player_service
from hcr2.services import sheets as sheet_service


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

    def test_donation_output_prints_mutation_statuses(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            donation_output.print_donation_added(1, "2025-11-15", 1200)
            donation_output.print_donation_deleted(7)
            donation_output.print_donation_updated(7, 1, "2025-11-15", 1200, 1500)
            donation_output.print_no_donation(9)
            donation_output.print_total_must_be_non_negative()
            donation_output.print_total_must_be_integer()
            donation_output.print_error(ValueError("bad input"))
            donation_output.print_player_not_found()
            donation_output.print_no_player_donations("Alice")
            donation_output.print_no_active_players()
            donation_output.print_no_donations_in_database()
            donation_output.print_no_active_plte_players()
            donation_output.print_no_under_index_players()
            donation_output.print_no_donations_found()
            donation_output.print_invalid_date_format()
            donation_output.print_no_donations_for_date("2025-11-15")

        output = buffer.getvalue()
        self.assertIn("✅ Donation snapshot added for player 1 on 2025-11-15 (total: 1200)", output)
        self.assertIn("✅ Donation 7 deleted", output)
        self.assertIn("✅ Donation 7 updated for player 1 on 2025-11-15: 1200 -> 1500", output)
        self.assertIn("ℹ️ No donation with id 9 found.", output)
        self.assertIn("❌ total must be >= 0", output)
        self.assertIn("❌ total must be an integer", output)
        self.assertIn("❌ Error: bad input", output)
        self.assertIn("❌ Player not found.", output)
        self.assertIn("ℹ️ No donations found for Alice.", output)
        self.assertIn("ℹ️ No active players.", output)
        self.assertIn("ℹ️ No donations found in database.", output)
        self.assertIn("ℹ️ No active players in team PLTE.", output)
        self.assertIn("ℹ️ No players with donation index below 100 in team PLTE.", output)
        self.assertIn("ℹ️ No donations found.", output)
        self.assertIn("❌ Invalid date format. Use YYYY-MM-DD or ISO 8601.", output)
        self.assertIn("ℹ️ No donations found for date 2025-11-15.", output)

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

    def test_player_output_prints_grep_and_resolution_statuses(self) -> None:
        rows = [PlayerSearchRow(id=1, name="Alice", alias="alice", garage_power=5000, active=1, discord_name="alice#1")]
        ambiguous = player_service.PlayerResolutionResult("AMBIGUOUS", matches=rows)
        missing = player_service.PlayerResolutionResult("NOT_FOUND", matches=[])

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_grep_result("nobody", [])
            print_grep_result("ali", rows)
            print_player_resolution_result(missing, "nobody")
            print_player_resolution_result(ambiguous, "ali")

        output = buffer.getvalue()
        self.assertIn("❌ No players found matching 'nobody'", output)
        self.assertIn("ID   NAME", output)
        self.assertIn("⚠️  Term 'ali' is not unique. Matching players:", output)

    def test_player_output_prints_explicit_resolution_statuses(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_explicit_player_resolution_result(player_service.ExplicitPlayerResolutionResult("INVALID_ID"))
            print_explicit_player_resolution_result(
                player_service.ExplicitPlayerResolutionResult("DISCORD_NOT_FOUND"),
                discord_name="alice#1",
            )
            print_explicit_player_resolution_result(
                player_service.ExplicitPlayerResolutionResult("DISCORD_AMBIGUOUS"),
                discord_name="ali",
            )
            print_explicit_player_resolution_result(
                player_service.ExplicitPlayerResolutionResult("NAME_AMBIGUOUS"),
                player_name="ali",
            )
            print_explicit_player_resolution_result(
                player_service.ExplicitPlayerResolutionResult("NOT_FOUND"),
                player_name="nobody",
            )
            print_explicit_player_resolution_result(player_service.ExplicitPlayerResolutionResult("MISSING_SELECTOR"))

        output = buffer.getvalue()
        self.assertIn("❌ Invalid --id value", output)
        self.assertIn("❌ No player found for discord_name='alice#1'", output)
        self.assertIn("⚠️ Multiple players match 'ali'.", output)
        self.assertIn("❌ No players found matching 'nobody'", output)
        self.assertIn("❌ Provide one of --id, --name, or --discord", output)

    def test_player_output_prints_leaders(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_player_leaders([PlayerLeaderRow(id=1, name="Alice", discord_name="alice#1")])
            print_player_leaders([])
        self.assertIn("ID   Name", buffer.getvalue())
        self.assertIn("👑 Leaders: 1", buffer.getvalue())
        self.assertIn("❌ No leaders found.", buffer.getvalue())

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

    def test_player_output_prints_birthday_outputs(self) -> None:
        result = player_service.PlayerBirthdayListResult(
            rows=[
                (
                    3,
                    PlayerBirthdayRow(
                        id=1,
                        name="Alice",
                        birthday="01-15",
                        emoji="🎂",
                        active=1,
                    ),
                )
            ],
            active_only=True,
        )

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_birthday_ids([1, 2])
            print_birthday_list(result)

        output = buffer.getvalue()
        self.assertIn("BIRTHDAY_IDS: 1,2", output)
        self.assertIn("ID   Name", output)
        self.assertIn("Alice", output)
        self.assertIn("15.01.", output)
        self.assertIn("Count: 1 (active only)", output)

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

    def test_player_output_prints_add_result_statuses(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_add_player_result(player_service.AddPlayerResult("INVALID_TEAM"), "Alice")
            print_add_player_result(player_service.AddPlayerResult("ALIAS_GENERATION_FAILED", alias_base="alice"), "Alice")
            print_add_player_result(player_service.AddPlayerResult("ALIAS_CONFLICT", alias="alice"), "Alice")
            print_add_player_result(
                player_service.AddPlayerResult(
                    "ADDED",
                    player_id=3,
                    alias="alice1",
                    alias_generated=True,
                    team="PLTE",
                ),
                "Alice",
            )

        output = buffer.getvalue()
        self.assertIn("❌ Invalid team name. Allowed: PLTE or PL1–PL9", output)
        self.assertIn("❌ Could not generate unique alias for base 'alice'", output)
        self.assertIn("❌ Alias conflict in PLTE: 'alice' already exists.", output)
        self.assertIn("✅ Player 'Alice' added. ID: 3 | Alias: alice1 (generated) | Team: PLTE", output)

    def test_player_output_prints_edit_result_statuses(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertFalse(print_edit_player_result(player_service.EditPlayerResult("NOT_FOUND"), 7))
            self.assertFalse(print_edit_player_result(player_service.EditPlayerResult("ALIAS_REQUIRED"), 7))
            self.assertFalse(
                print_edit_player_result(
                    player_service.EditPlayerResult(
                        "ALIAS_CONFLICT",
                        alias="ali",
                        conflict_alias="alice",
                        conflict_player_id=1,
                    ),
                    7,
                )
            )
            self.assertFalse(print_edit_player_result(player_service.EditPlayerResult("NOTHING_TO_UPDATE"), 7))
            self.assertTrue(print_edit_player_result(player_service.EditPlayerResult("UPDATED"), 7))

        output = buffer.getvalue()
        self.assertIn("❌ Player ID 7 not found.", output)
        self.assertIn("❌ Alias is required for team PLTE.", output)
        self.assertIn("❌ Alias conflict: 'ali' vs 'alice' (ID 1)", output)
        self.assertIn("⚠️  Nothing to update.", output)
        self.assertIn("✅ Player 7 updated.", output)

    def test_player_output_prints_activation_statuses(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_player_deactivated(7)
            print_player_deleted(7)
            print_player_activated(7)

        self.assertEqual(
            buffer.getvalue(),
            "🟡 Player 7 deactivated.\n"
            "🗑️  Player 7 deleted.\n"
            "🟢 Player 7 activated.\n",
        )

    def test_player_output_prints_validation_statuses(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            print_invalid_id()
            print_no_matching_player()
            print_player_id_not_found(7)
            print_single_selector_required()
            print_gp_requires_integer()
            print_num_requires_integer()
            print_name_required()
            print_invalid_team_name()
            print_invalid_team_value("BAD")
            print_invalid_birthday_format("31-12")
            print_active_requires_bool()
            print_leader_requires_bool()
            print_away_selector_required()
            print_value_error(ValueError("bad duration"))

        output = buffer.getvalue()
        self.assertIn("❌ Invalid ID.", output)
        self.assertIn("❌ No matching player found.", output)
        self.assertIn("❌ Player ID 7 not found.", output)
        self.assertIn("❌ Provide exactly one of --id, --name or --discord.", output)
        self.assertIn("❌ --gp expects an integer.", output)
        self.assertIn("❌ --num expects an integer", output)
        self.assertIn("❌ Name is required.", output)
        self.assertIn("❌ Invalid team name. Allowed: PLTE or PL1–PL9", output)
        self.assertIn("❌ Invalid team name: BAD (allowed: PLTE or PL1–PL9)", output)
        self.assertIn("❌ Invalid birthday format: 31-12 (use DD.MM.)", output)
        self.assertIn("❌ --active expects true|false", output)
        self.assertIn("❌ --leader expects true|false", output)
        self.assertIn("❌ Provide one of --id, --name, --discord or use the short form with a term.", output)
        self.assertIn("❌ bad duration", output)

    def test_stats_output_prints_perf_table(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats_output.print_perf_table([("Alice", 5000, 1)])
        self.assertIn("Lady", buffer.getvalue())
        self.assertIn("Alice", buffer.getvalue())
        self.assertIn("5.0k", buffer.getvalue())

    def test_stats_output_prints_perf_statuses_and_aliases(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats_output.print_no_matching_season()
            stats_output.print_perf_header(7, "Summer", "D1")
            stats_output.print_required_matches(15, 3)
            stats_output.print_no_match_scores()
            stats_output.print_no_active_plte_players()
            stats_output.print_no_perf_entries(active_only=True, min_matches=1)
            stats_output.print_no_perf_entries(active_only=False, min_matches=3)
            stats_output.print_aliases(["alice", "betty"])

        output = buffer.getvalue()
        self.assertIn("⚠️ No matching season found.", output)
        self.assertIn("📈Performance Season 7 (Summer) DIV: D1", output)
        self.assertIn("ℹ️ Required matches: 3/15 (20%)", output)
        self.assertIn("⚠️ No match scores found.", output)
        self.assertIn("⚠️ No active PLTE players.", output)
        self.assertIn("⚠️ No active players with scored matches found.", output)
        self.assertIn("⚠️ No players with at least 3 scored matches found.", output)
        self.assertTrue(output.endswith("alice\nbetty\n"))

    def test_stats_output_prints_sum_metric_table(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats_output.print_sum_metric_header("score", 7, "Summer", "D1")
            stats_output.print_sum_metric_header("points", 8, "Winter", "")
            stats_output.print_sum_metric_table([("Alice", 50000, 1), ("Betty", None, 0)], metric="score")
        output = buffer.getvalue()
        self.assertIn("📊Score Season 7 (Summer) DIV: D1", output)
        self.assertIn("📊Points Season 8 (Winter) DIV:", output)
        self.assertIn("Score", output)
        self.assertIn("Alice", output)
        self.assertIn("50000", output)
        self.assertIn("-", output)

    def test_stats_output_prints_plot_statuses(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats_output.print_no_data()
            stats_output.print_no_season()
            stats_output.print_no_matches_found()
            stats_output.print_scatter_plot("scatter")
            stats_output.print_birthday_plot("birthday")

        self.assertEqual(
            buffer.getvalue(),
            "⚠️ No data.\n"
            "⚠️ No season.\n"
            "⚠️ No matches found.\n"
            "scatter\n"
            "birthday\n",
        )

    def test_stats_output_prints_teamevent_statuses(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats_output.print_no_teamevent_for_offset(2)
            stats_output.print_no_teamevent(7)
            stats_output.print_no_teamevent_scores(7)
            stats_output.print_no_valid_teamevent_scores(7)
            stats_output.print_no_teamevent_rank_data(7)
            stats_output.print_teamevent_perf_header(7, "Teamcup", 2021, 21)

        output = buffer.getvalue()
        self.assertIn("⚠️ No team event found for offset 2.", output)
        self.assertIn("⚠️ No team event with id 7 found.", output)
        self.assertIn("⚠️ No match scores for team event 7.", output)
        self.assertIn("⚠️ No valid scores for PLTE players in team event 7.", output)
        self.assertIn("⚠️ No data to rank for team event 7.", output)
        self.assertIn("📊 Performance Team Event 7: Teamcup (2021-W21)", output)

    def test_stats_output_prints_player_statuses(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            stats_output.print_no_player(7)
            stats_output.print_no_player_matches(7)

        self.assertEqual(
            buffer.getvalue(),
            "⚠️ No player with id 7.\n"
            "⚠️ No matches found for player 7.\n",
        )

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

    def test_excel_exporter_builds_match_sheet_workbook(self) -> None:
        match = (7, "2021-06-05", 62, "Fast Opps #1", "Team Cup!")
        players = [(1, "Alice", None, None), (2, "Betty", "2021-06-01", "2021-06-10")]

        wb = excel_exporter.build_match_sheet_workbook(
            match,
            players,
            is_absent_on=lambda match_day, away_from, away_until: away_from is not None,
        )

        ws = wb.active
        self.assertEqual(ws.title, "Match Info")
        self.assertEqual(ws["A1"].value, "Match ID: 7")
        self.assertEqual(ws["E2"].value, "<-- Fast Opps #1")
        self.assertEqual([ws["A3"].value, ws["B3"].value, ws["C3"].value], ["MatchID", "PlayerID", "Player"])
        self.assertEqual([ws["A4"].value, ws["B4"].value, ws["C4"].value, ws["F4"].value], [7, 1, "Alice", "false"])
        self.assertEqual([ws["A5"].value, ws["B5"].value, ws["C5"].value, ws["F5"].value], [7, 2, "Betty", "true"])

    def test_excel_exporter_saves_and_deletes_workbook(self) -> None:
        wb = excel_exporter.build_players_workbook(["id", "name"], [(1, "Alice")])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "players.xlsx"

            saved_path = excel_exporter.save_workbook(wb, path)

            self.assertEqual(saved_path, path)
            self.assertTrue(path.exists())
            self.assertTrue(excel_exporter.delete_local_file(path))
            self.assertFalse(path.exists())
            self.assertFalse(excel_exporter.delete_local_file(path))

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
            matchscore_output.print_delete_result(matchscore_service.DeleteScoreResult(_matchscore_detail()))
            matchscore_output.print_delete_result(matchscore_service.DeleteScoreResult(None))
        self.assertEqual(
            buffer.getvalue(),
            "OK DELETED:\n"
            "ID=1 match=1 date=2021-06-05 opp=Rivals player=Alice score=50000 points=200 absent=0 checkin=1\n"
            "⚠️ Not found.\n",
        )

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            matchscore_output.print_no_scores_found()
        self.assertEqual(buffer.getvalue(), "⚠️ No scores found.\n")

    def test_matchscore_output_prints_edit_result(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            matchscore_output.print_updated_score(_matchscore_detail())
        output = buffer.getvalue()
        self.assertIn("OK UPDATED:", output)
        self.assertIn("Match 1 – Rivals | 2021-06-05", output)
        self.assertIn("ID     Player           Score Pts Abs Cin", output)
        self.assertIn("1      Alice            50000 200   0   1", output)

    def test_matchscore_output_prints_add_statuses(self) -> None:
        ambiguous = matchscore_service.AddScoreResult(
            "PLAYER_AMBIGUOUS",
            matchscore_service.PlayerResolution(
                player_id=None,
                matches=[PlayerLookup(1, "Alice", "ali"), PlayerLookup(2, "Alicia", "alice2")],
            ),
        )

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            matchscore_output.print_invalid_score_or_points()
            matchscore_output.print_add_result(matchscore_service.AddScoreResult("INVALID_RANGE"), "Alice")
            matchscore_output.print_add_result(matchscore_service.AddScoreResult("PLAYER_NOT_FOUND"), "Nobody")
            matchscore_output.print_add_result(ambiguous, "Ali")
            matchscore_output.print_add_result(matchscore_service.AddScoreResult("CHANGED"), "Alice")

        output = buffer.getvalue()
        self.assertIn("❌ Score or points out of valid range.", output)
        self.assertIn("❌ No player found matching: Nobody", output)
        self.assertIn("⚠️ Multiple players found for 'Ali':", output)
        self.assertIn("ID 1: Alice (alias: ali)", output)
        self.assertIn("CHANGED", output)

    def test_matchscore_output_prints_edit_statuses(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            matchscore_output.print_pid_requires_numeric()
            matchscore_output.print_edit_result(matchscore_service.EditScoreResult("NOTHING_TO_UPDATE"))
            matchscore_output.print_edit_result(matchscore_service.EditScoreResult("NOT_FOUND"))
            matchscore_output.print_edit_result(matchscore_service.EditScoreResult("PLAYER_NOT_FOUND", player_id=99))
            matchscore_output.print_edit_result(
                matchscore_service.EditScoreResult("PLAYER_CLASH", player_id=2, clash_id=5, match_id=1)
            )
            matchscore_output.print_edit_result(matchscore_service.EditScoreResult("SCORE_OUT_OF_RANGE"))
            matchscore_output.print_edit_result(matchscore_service.EditScoreResult("POINTS_OUT_OF_RANGE"))

        output = buffer.getvalue()
        self.assertIn("❌ --pid requires a numeric player_id.", output)
        self.assertIn("⚠️ Nothing to update.", output)
        self.assertIn("⚠️ Not found.", output)
        self.assertIn("❌ Player id 99 does not exist.", output)
        self.assertIn("matchscore.id=5", output)
        self.assertIn("❌ Score out of range.", output)
        self.assertIn("❌ Points out of range.", output)

    def test_sheet_output_prints_export_and_import_results(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            sheet_output.print_exported_workbook(
                "Power-Ladys-Scores/Ladys.xlsx",
                "https://example.test/scores",
                True,
            )
            sheet_output.print_match_sheet_link_created("[7_Event_Opp.xlsx](https://example.test/S62)", False)
            sheet_output.print_match_import_result(
                "7_Event_Opp.xlsx",
                "https://example.test/S62",
                sheet_service.MatchSheetApplyResult(imported=2, changed=1, score_updated=True),
            )
            sheet_output.print_player_import_result(
                sheet_service.PlayerImportResult(updated=1, inserted=2, skipped=3, errors=4),
                "deleted",
            )
            sheet_output.print_donation_import_result(
                sheet_service.DonationImportResult(added=5, errors=6),
                "delete failed",
            )

        output = buffer.getvalue()
        self.assertIn("✅ [Power-Ladys-Scores/Ladys.xlsx](https://example.test/scores) (Created)", output)
        self.assertIn("✅ [7_Event_Opp.xlsx](https://example.test/S62) (Already existed)", output)
        self.assertIn("✅ [7_Event_Opp.xlsx](https://example.test/S62) (Changed, 2 imported, 1 changed; Score updated)", output)
        self.assertIn("✅ players import: 1 updated, 2 inserted, 3 skipped, 4 errors (deleted in Nextcloud)", output)
        self.assertIn("✅ donations import: 5 added, 6 errors (delete failed in Nextcloud)", output)

    def test_sheet_output_prints_match_import_renames(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            sheet_output.print_match_import_result(
                "7_Event_Opp.xlsx",
                "https://example.test/S62",
                sheet_service.MatchSheetApplyResult(
                    imported=2,
                    changed=1,
                    score_updated=True,
                    renamed=[(1, "Alice", "Alice Cooper")],
                    rename_errors=["Row 9: kept stored name for player 4 (rename rejected: ALIAS_CONFLICT)"],
                ),
            )

        output = buffer.getvalue()
        self.assertIn("(Changed, 2 imported, 1 changed; 1 renamed; Score updated)", output)
        self.assertIn("✏️ Player 1: 'Alice' → 'Alice Cooper'", output)
        self.assertIn("⚠️ Row 9: kept stored name for player 4 (rename rejected: ALIAS_CONFLICT)", output)

    def test_sheet_output_prints_validation_errors(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            sheet_output.print_validation_errors(["Row 4: bad score", "Row 5: bad points"])

        self.assertEqual(
            buffer.getvalue(),
            "❌ Import aborted due to validation errors:\n"
            " - Row 4: bad score\n"
            " - Row 5: bad points\n",
        )

    def test_sheet_output_prints_status_errors(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            sheet_output.print_no_match_found()
            sheet_output.print_match_excel_not_found()
            sheet_output.print_players_table_not_found()
            sheet_output.print_players_excel_not_found()
            sheet_output.print_invalid_players_header()
            sheet_output.print_donations_excel_not_found()
            sheet_output.print_invalid_donations_date()
            sheet_output.print_invalid_match_id()

        output = buffer.getvalue()
        self.assertIn("❌ No match found.", output)
        self.assertIn("❌ match Excel not found on Nextcloud", output)
        self.assertIn("❌ players table not found", output)
        self.assertIn("❌ players Excel not found on Nextcloud", output)
        self.assertIn("❌ First row must contain column names including 'id'", output)
        self.assertIn("❌ donations Excel not found on Nextcloud", output)
        self.assertIn("❌ No valid date in cell A2", output)
        self.assertIn("❌ Match ID must be an integer.", output)


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
