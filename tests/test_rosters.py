from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from hcr2.models.roster import RosterReading, RosterVideo
from hcr2.services import rosters as roster_service
from tests.support import TemporaryDatabaseTestCase


class TypeableNameTests(unittest.TestCase):
    def test_umlauts_are_fine_but_decoration_is_not(self) -> None:
        self.assertEqual(roster_service.untypeable_characters("Abräumer"), [])
        self.assertEqual(roster_service.untypeable_characters("PL|Deer-Lady"), [])
        self.assertEqual(roster_service.untypeable_characters("CLO$ED"), [])
        self.assertEqual(roster_service.untypeable_characters("£@π"), ["£", "π"])
        self.assertEqual(roster_service.untypeable_characters("Fox 🦊"), ["🦊"])


class CandidateScoreTests(unittest.TestCase):
    def test_a_shortened_name_scores_above_a_coincidental_ratio(self) -> None:
        shortened = roster_service.candidate_score("Bisa", "BisaTheWise")
        coincidence = roster_service.candidate_score("Bisa", "ASA")
        self.assertGreaterEqual(shortened, roster_service.CONTAINMENT_SCORE)
        self.assertGreater(shortened, coincidence)

    def test_a_three_letter_stem_is_not_enough_for_containment(self) -> None:
        self.assertLess(roster_service.candidate_score("Leo", "Leonardo"), roster_service.CONTAINMENT_SCORE)


class RosterFileTests(unittest.TestCase):
    def test_broken_json_is_reported(self) -> None:
        with mock.patch.object(Path, "read_text", return_value="{nope"):
            video, errors = roster_service.load_readings(Path("roster.json"))
        self.assertIsNone(video)
        self.assertIn("not valid JSON", errors[0])

    def test_garage_power_with_a_thousand_separator_is_read(self) -> None:
        payload = {"member_count": 1, "players": [{"name": "Alice", "garage_power": "15 354"}]}
        with mock.patch.object(Path, "read_text", return_value=json.dumps(payload)):
            video, errors = roster_service.load_readings(Path("roster.json"))
        self.assertEqual(errors, [])
        self.assertEqual(video.players[0].garage_power, 15354)
        self.assertEqual(video.member_count, 1)


class RosterPlanTests(TemporaryDatabaseTestCase):
    """Fixture: Alice (1) active PLTE gp 5000; Betty (2) inactive, team PL1."""

    def video(self, players, **overrides) -> RosterVideo:
        return RosterVideo(
            players=players,
            team="Power-Ladys",
            member_count=overrides.get("member_count", len(players)),
        )

    def test_a_changed_garage_power_becomes_one_change(self) -> None:
        plan = roster_service.build_plan(self.video([RosterReading(name="Alice", garage_power=5500)]))
        self.assertEqual(plan.status, "READY")
        self.assertEqual([(c.kind, c.player_id) for c in plan.changes], [("GP", 1)])

    def test_an_unchanged_row_produces_nothing(self) -> None:
        plan = roster_service.build_plan(self.video([RosterReading(name="Alice", garage_power=5000)]))
        self.assertEqual(plan.changes, [])
        self.assertEqual(plan.unchanged, 1)

    def test_a_dropping_garage_power_is_worth_a_note(self) -> None:
        plan = roster_service.build_plan(self.video([RosterReading(name="Alice", garage_power=4000)]))
        self.assertTrue(any("dropped" in note for note in plan.notes))

    def test_a_member_count_that_disagrees_stops_the_import(self) -> None:
        plan = roster_service.build_plan(
            self.video([RosterReading(name="Alice", garage_power=5000)], member_count=2)
        )
        self.assertEqual(plan.status, "ERRORS")
        self.assertTrue(any("a row was missed" in error for error in plan.errors))

    def test_an_untypeable_name_stops_the_import(self) -> None:
        plan = roster_service.build_plan(self.video([RosterReading(name="Al£ce", garage_power=5000)]))
        self.assertEqual(plan.status, "ERRORS")
        self.assertTrue(any("German keyboard" in error for error in plan.errors))

    def test_an_unknown_name_waits_for_a_decision(self) -> None:
        plan = roster_service.build_plan(
            self.video([RosterReading(name="Alice", garage_power=5000), RosterReading(name="Newbie", garage_power=6000)])
        )
        self.assertEqual(plan.status, "PENDING")
        self.assertEqual([p.reading.name for p in plan.pending], ["Newbie"])
        self.assertEqual(roster_service.apply_plan(plan, self.video([])).status, "PENDING")

    def test_the_player_who_vanished_leads_the_candidate_list(self) -> None:
        plan = roster_service.build_plan(self.video([RosterReading(name="Newbie", garage_power=6000)]))
        candidates = plan.pending[0].candidates
        self.assertEqual(candidates[0].player_id, 1)
        self.assertEqual(candidates[0].name, "Alice")

    def test_a_decided_new_member_is_added_and_the_leaver_deactivated(self) -> None:
        plan = roster_service.build_plan(
            self.video([RosterReading(name="Newbie", garage_power=6000, new=True)])
        )
        self.assertEqual(plan.status, "READY")
        applied = roster_service.apply_plan(
            plan, self.video([RosterReading(name="Newbie", garage_power=6000, new=True)])
        )
        self.assertEqual(applied.status, "APPLIED")
        self.assertEqual(self.active_names(), ["Newbie"])

    def test_reactivating_an_already_active_player_renames_instead_of_deactivating(self) -> None:
        reading = RosterReading(name="Alicia", garage_power=5500, reactivate=1)
        plan = roster_service.build_plan(self.video([reading]))
        kinds = sorted(change.kind for change in plan.changes)
        self.assertEqual(kinds, ["GP", "RENAME"])
        self.assertNotIn("DEACTIVATE", [c.kind for c in plan.changes])

        applied = roster_service.apply_plan(plan, self.video([reading]))
        self.assertTrue(all(change.status == "OK" for change in applied.changes), applied.changes)
        self.assertEqual(self.active_names(), ["Alicia"])
        self.assertEqual(self.garage_power(1), 5500)

    def test_a_returning_player_is_reactivated(self) -> None:
        reading = RosterReading(name="Betty", garage_power=7000, reactivate=2)
        video = self.video([RosterReading(name="Alice", garage_power=5000), reading])
        plan = roster_service.build_plan(video)
        self.assertIn("REACTIVATE", [c.kind for c in plan.changes])

        applied = roster_service.apply_plan(plan, video)
        self.assertTrue(all(c.status == "OK" for c in applied.changes), applied.changes)
        self.assertEqual(sorted(self.active_names()), ["Alice", "Betty"])

    def active_names(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            return [row[0] for row in conn.execute(
                "SELECT name FROM players WHERE active = 1 AND team = 'PLTE' ORDER BY name"
            )]

    def garage_power(self, player_id: int) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT garage_power FROM players WHERE id = ?", (player_id,)).fetchone()[0]


if __name__ == "__main__":
    unittest.main()
