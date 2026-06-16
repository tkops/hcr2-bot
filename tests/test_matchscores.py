from __future__ import annotations

import sqlite3

from hcr2.repositories import matches as match_repo
from hcr2.repositories import matchscores as matchscore_repo
from hcr2.services import matchscores as matchscore_service
from tests.support import TemporaryDatabaseTestCase


class MatchscoreTests(TemporaryDatabaseTestCase):
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
