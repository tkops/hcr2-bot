from __future__ import annotations

import unittest

from hcr2.repositories import distances as distance_repo
from hcr2.repositories import players as player_repo
from hcr2.services import distances as distance_service
from hcr2.services import deletions as deletion_service
from tests.support import TemporaryDatabaseTestCase


class DistanceServiceTests(TemporaryDatabaseTestCase):
    """Fixture: Alice (1) active PLTE, Betty (2) inactive."""

    def test_a_week_is_stored_and_corrected_in_place(self) -> None:
        first = distance_service.add_distance(player_input="1", year=2026, week=34, km=317)
        self.assertEqual(first.status, "ADDED")
        distance_service.add_distance(player_input="1", year=2026, week=34, km=320)

        rows = distance_service.ranking(2026, 34)
        self.assertEqual([(row.player_id, row.km) for row in rows], [(1, 320)])

    def test_kilometres_outside_the_range_are_rejected(self) -> None:
        self.assertEqual(distance_service.add_distance(player_input="1", year=2026, week=34, km=-1).status, "INVALID_RANGE")
        self.assertEqual(
            distance_service.add_distance(player_input="1", year=2026, week=34, km=99999).status, "INVALID_RANGE"
        )

    def test_an_impossible_week_is_rejected(self) -> None:
        self.assertEqual(distance_service.add_distance(player_input="1", year=2026, week=54, km=10).status, "INVALID_WEEK")

    def test_an_unknown_player_is_reported(self) -> None:
        self.assertEqual(distance_service.add_distance(player_input="999", year=2026, week=34, km=10).status, "PLAYER_NOT_FOUND")

    def test_the_ranking_carries_each_players_own_average(self) -> None:
        for week, km in ((32, 100), (33, 200), (34, 300)):
            distance_service.add_distance(player_input="1", year=2026, week=week, km=km)
        row = distance_service.ranking(2026, 34)[0]
        self.assertEqual(row.km, 300)
        self.assertAlmostEqual(row.average, 200.0)
        self.assertEqual(row.weeks, 3)

    def test_history_reports_the_rank_within_each_week(self) -> None:
        distance_service.add_distance(player_input="1", year=2026, week=34, km=100)
        distance_service.add_distance(player_input="2", year=2026, week=34, km=300)
        rows = distance_service.history(1)
        self.assertEqual((rows[0].rank, rows[0].of), (2, 2))

    def test_weeks_sum_the_team_total(self) -> None:
        distance_service.add_distance(player_input="1", year=2026, week=34, km=100)
        distance_service.add_distance(player_input="2", year=2026, week=34, km=300)
        week = distance_service.weeks()[0]
        self.assertEqual((week.total, week.players), (400, 2))

    def test_resolve_week_falls_back_to_the_latest_stored_one(self) -> None:
        distance_service.add_distance(player_input="1", year=2026, week=34, km=100)
        self.assertEqual(distance_service.resolve_week(None, None), (2026, 34))
        self.assertEqual(distance_service.resolve_week(2025, 3), (2025, 3))
        self.assertIsNone(distance_service.resolve_week(2026, None))


class DistanceImportTests(TemporaryDatabaseTestCase):
    def test_the_chest_total_has_to_match_the_sum(self) -> None:
        result = distance_service.import_week(
            year=2026, week=34, entries=[{"pid": 1, "km": 100}], team_total=150
        )
        self.assertEqual(result.status, "ERRORS")
        self.assertTrue(any("a row was missed" in error for error in result.errors))

    def test_force_downgrades_the_total_check(self) -> None:
        result = distance_service.import_week(
            year=2026, week=34, entries=[{"pid": 1, "km": 100}], team_total=150, force=True
        )
        self.assertEqual(result.status, "IMPORTED")
        self.assertTrue(any("[forced]" in warning for warning in result.warnings))

    def test_duplicates_and_unknown_players_are_rejected(self) -> None:
        result = distance_service.import_week(
            year=2026, week=34, entries=[{"pid": 1, "km": 10}, {"pid": 1, "km": 20}]
        )
        self.assertTrue(any("more than once" in error for error in result.errors))
        self.assertEqual(distance_service.ranking(2026, 34), [])

    def test_a_matching_total_imports_every_row(self) -> None:
        result = distance_service.import_week(
            year=2026, week=34, entries=[{"pid": 1, "km": 100}, {"pid": 2, "km": 300}], team_total=400
        )
        self.assertEqual((result.status, result.imported, result.total), ("IMPORTED", 2, 400))


class DistanceProfileTests(TemporaryDatabaseTestCase):
    def test_the_profile_averages_the_recent_weeks(self) -> None:
        for week, km in ((32, 100), (33, 200), (34, 300)):
            distance_service.add_distance(player_input="1", year=2026, week=week, km=km)
        detail = player_repo.get_player_detail(1)
        self.assertEqual(detail.km_weeks, 3)
        self.assertAlmostEqual(detail.avg_km, 200.0)

    def test_a_player_without_kilometres_shows_no_average(self) -> None:
        detail = player_repo.get_player_detail(1)
        self.assertEqual((detail.km_weeks, detail.avg_km), (0, 0.0))

    def test_the_average_window_is_shared_with_the_ranking(self) -> None:
        self.assertEqual(player_repo.DISTANCE_AVERAGE_WINDOW, distance_repo.AVERAGE_WINDOW)


class DistanceDeleteGuardTests(TemporaryDatabaseTestCase):
    def test_a_player_with_kilometres_cannot_be_deleted(self) -> None:
        distance_service.add_distance(player_input="1", year=2026, week=34, km=100)
        outcome = deletion_service.delete_player(1)
        self.assertEqual(outcome.status, "BLOCKED")
        self.assertIn("distance entry", " ".join(label for label, _ in outcome.blocks))


if __name__ == "__main__":
    unittest.main()
