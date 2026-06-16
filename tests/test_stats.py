from __future__ import annotations

import sqlite3
from unittest import mock

from hcr2.output import stats as stats_output
from hcr2.repositories import stats as stats_repo
from hcr2.services import stats as stats_service
from modules import stats
from tests.support import TemporaryDatabaseTestCase


class StatsTests(TemporaryDatabaseTestCase):
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
