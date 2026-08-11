from __future__ import annotations

import sqlite3

from hcr2.output import deletions as deletions_output
from hcr2.services import deletions as deletions_service
from modules import match, player, season, teamevent
from tests.support import TemporaryDatabaseTestCase


class DeletionGuardTests(TemporaryDatabaseTestCase):
    """The fixture has player 1 with a matchscore, match 1 in season 2, teamevent 1."""

    def test_player_with_scores_is_not_deletable(self) -> None:
        outcome = deletions_service.delete_player(1)

        self.assertEqual(outcome.status, "BLOCKED")
        self.assertEqual(outcome.blocks, [("match score", 1)])
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM players WHERE id=1").fetchone()[0], 1)

    def test_player_without_dependencies_is_deletable(self) -> None:
        outcome = deletions_service.delete_player(2)

        self.assertEqual(outcome.status, "DELETED")
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM players WHERE id=2").fetchone()[0], 0)

    def test_match_season_and_teamevent_are_blocked_by_dependents(self) -> None:
        self.assertEqual(deletions_service.delete_match(1).blocks, [("match score", 1)])
        self.assertEqual(deletions_service.delete_season(2).blocks, [("match", 1)])
        self.assertEqual(deletions_service.delete_teamevent(1).blocks, [("match", 1)])
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM match WHERE id=1").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM season WHERE number=2").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM teamevent WHERE id=1").fetchone()[0], 1)

    def test_deleting_in_dependency_order_succeeds(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM matchscore WHERE match_id = 1")

        self.assertEqual(deletions_service.delete_match(1).status, "DELETED")
        self.assertEqual(deletions_service.delete_season(2).status, "DELETED")
        self.assertEqual(deletions_service.delete_teamevent(1).status, "DELETED")

    def test_donations_also_block_player_deletion(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM matchscore WHERE player_id = 1")
            conn.execute("INSERT INTO donation (player_id, date, total) VALUES (1, '2026-01-01', 5)")

        outcome = deletions_service.delete_player(1)

        self.assertEqual(outcome.blocks, [("donation", 1)])

    def test_cli_delete_paths_report_the_blockers(self) -> None:
        for label, func, arg in (
            ("Player 1", player.delete_player, 1),
            ("Match 1", match.delete_match, 1),
            ("Team event 1", teamevent.delete_teamevent, 1),
        ):
            with self.subTest(label=label):
                output = self.capture_stdout(func, arg)
                self.assertIn(f"❌ {label} still has", output)
                self.assertIn("nothing was deleted", output)

        output = self.capture_stdout(season.delete_season, ["--number", "2"])
        self.assertIn("❌ Season 2 still has 1 match –", output)

    def test_unknown_ids_report_not_found_instead_of_success(self) -> None:
        for kind, func in (
            ("player", deletions_service.delete_player),
            ("match", deletions_service.delete_match),
            ("season", deletions_service.delete_season),
            ("teamevent", deletions_service.delete_teamevent),
        ):
            with self.subTest(kind=kind):
                outcome = func(999999)
                self.assertEqual(outcome.status, "NOT_FOUND")
                self.assertEqual(outcome.kind, kind)

    def test_cli_delete_of_unknown_id_prints_an_error(self) -> None:
        output = self.capture_stdout(match.delete_match, 999999)

        self.assertIn("❌ Match 999999 does not exist", output)
        self.assertNotIn("deleted.", output.replace("nothing was deleted", ""))

    def test_exists_covers_the_primary_key_of_every_kind(self) -> None:
        self.assertTrue(deletions_service.exists("player", 1))
        self.assertTrue(deletions_service.exists("match", 1))
        self.assertTrue(deletions_service.exists("season", 2))  # PK ist "number"
        self.assertTrue(deletions_service.exists("teamevent", 1))
        self.assertFalse(deletions_service.exists("season", 9999))

    def test_blocked_output_lists_every_blocker_with_a_hint(self) -> None:
        outcome = deletions_service.DeleteOutcome(
            status="BLOCKED",
            kind="player",
            key=42,
            blocks=[("match scores", 137), ("donations", 3)],
        )

        output = self.capture_stdout(deletions_output.print_delete_blocked, outcome)

        self.assertIn("❌ Player 42 still has 137 match scores, 3 donations", output)
        self.assertIn("matchscore edit <id> --player <id>", output)

    def test_every_dependency_target_exists_in_the_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for _kind, deps in deletions_service.DEPENDENCIES.items():
                for table, column, *_labels in deps:
                    with self.subTest(table=table, column=column):
                        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
                        self.assertIn(column, cols)
