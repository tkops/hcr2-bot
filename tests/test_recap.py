"""Tests for the match recap facts.

The recap text itself is written by the model and may read differently every time -
what these tests hold is the substance it is allowed to claim: who was on the podium,
how unusual that is for her, who really improved once the team's pace is taken out,
and what counts as a personal best.
"""
from __future__ import annotations

import re
import sqlite3

from hcr2.services import recap as recap_service
from hcr2.output import recap as recap_output
from tests.support import TemporaryDatabaseTestCase


# Five earlier matches plus the one under test - enough history for a personal best
# (MIN_MATCHES_FOR_RECORD) and for the podium window to mean something.
EARLIER = [100, 101, 102, 103, 104]
TARGET = 105

# player id -> score in each of the earlier matches
BASELINE = {10: 50000, 11: 40000, 12: 30000, 13: 20000, 14: 10000, 15: 9000}
# The target match: 15 jumps from 9000 onto the podium, 14 does not show up at all.
FINAL = {10: 50000, 11: 41000, 12: 30000, 13: 20000, 14: 0, 15: 45000}


class RecapTestCase(TemporaryDatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO players (id, name, team, active) VALUES (?, ?, 'PLTE', 1)",
                [(pid, f"P{pid}") for pid in BASELINE],
            )
            for offset, match_id in enumerate(EARLIER + [TARGET]):
                conn.execute(
                    """
                    INSERT INTO match (id, teamevent_id, season_number, start, opponent,
                                       score_ladys, score_opponent)
                    VALUES (?, 1, 2, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        f"2021-06-{10 + offset:02d}",
                        "Rivals" if match_id == TARGET else f"Team {match_id}",
                        200 if match_id == TARGET else 150,
                        100,
                    ),
                )
            for match_id in EARLIER:
                conn.executemany(
                    "INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin)"
                    " VALUES (?, ?, ?, 10, 0, 0)",
                    [(match_id, pid, score) for pid, score in BASELINE.items()],
                )
            conn.executemany(
                "INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin)"
                " VALUES (?, ?, ?, 10, 0, 0)",
                [(TARGET, pid, score) for pid, score in FINAL.items()],
            )


class RecapFactTests(RecapTestCase):
    def test_result_and_participation(self) -> None:
        recap = recap_service.build_recap(TARGET)
        self.assertEqual(recap.status, "OK")
        self.assertEqual(recap.result, "WIN")
        self.assertEqual(recap.margin, 100)
        self.assertEqual(recap.drivers, 5)
        self.assertEqual(recap.roster_rows, 6)
        self.assertFalse(recap.everyone_drove)
        self.assertEqual([(a.name, a.reason) for a in recap.absent], [("P14", "no-show")])

    def test_everyone_drove_is_only_true_without_a_zero_row(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE matchscore SET score = 11000 WHERE match_id = ? AND player_id = 14",
                (TARGET,),
            )
        recap = recap_service.build_recap(TARGET)
        self.assertTrue(recap.everyone_drove)
        self.assertEqual(recap.absent, [])

    def test_absence_reasons_stay_apart(self) -> None:
        """A holiday, a checked-in no-show and simply not turning up are three
        different sentences - the text must not be able to mix them up."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE matchscore SET absent = 1 WHERE match_id = ? AND player_id = 14",
                (TARGET,),
            )
            conn.execute(
                "INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin)"
                " VALUES (?, 1, 0, 0, 0, 1)",
                (TARGET,),
            )
        reasons = {entry.name: entry.reason for entry in recap_service.build_recap(TARGET).absent}
        self.assertEqual(reasons, {"P14": "away", "Alice": "checkin"})


class PodiumTests(RecapTestCase):
    def test_podium_is_the_top_three_by_score(self) -> None:
        recap = recap_service.build_recap(TARGET)
        self.assertEqual([(e.rank, e.name, e.score) for e in recap.podium],
                         [(1, "P10", 50000), (2, "P15", 45000), (3, "P11", 41000)])

    def test_a_regular_is_not_marked_notable(self) -> None:
        """P10 won every earlier match. Celebrating that every two days is what makes
        the praise for a rare podium worthless."""
        entry = recap_service.build_recap(TARGET).podium[0]
        self.assertEqual(entry.podiums_in_window, len(EARLIER))
        self.assertFalse(entry.notable)
        self.assertFalse(entry.first_ever)
        self.assertEqual(entry.matches_since_last, 1)

    def test_a_first_podium_is_flagged(self) -> None:
        entry = next(e for e in recap_service.build_recap(TARGET).podium if e.name == "P15")
        self.assertTrue(entry.first_ever)
        self.assertTrue(entry.notable)
        self.assertEqual(entry.podiums_in_window, 0)
        self.assertIsNone(entry.matches_since_last)

    def test_notable_follows_the_share_of_the_window(self) -> None:
        share = recap_service.RARE_PODIUM_SHARE
        recap = recap_service.build_recap(TARGET)
        for entry in recap.podium:
            self.assertEqual(entry.notable, entry.podiums_in_window / entry.window <= share)


class ImprovementTests(RecapTestCase):
    def test_improvement_is_measured_against_the_team_pace(self) -> None:
        """Everybody gaining the same amount is the event getting easier, not five
        personal triumphs - only the one who gained on the others shows up."""
        recap = recap_service.build_recap(TARGET)
        names = [entry.name for entry in recap.improvements]
        self.assertEqual(names[0], "P15")
        self.assertNotIn("P12", names)
        self.assertNotIn("P13", names)

    def test_a_uniform_lift_produces_no_improvements(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for pid, score in BASELINE.items():
                conn.execute(
                    "UPDATE matchscore SET score = ? WHERE match_id = ? AND player_id = ?",
                    (int(score * 1.5), TARGET, pid),
                )
        self.assertEqual(recap_service.build_recap(TARGET).improvements, [])

    def test_no_pace_without_enough_drivers(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE match_id = ? AND player_id > 11", (TARGET,)
            )
        recap = recap_service.build_recap(TARGET)
        self.assertEqual(recap.improvements, [])
        self.assertTrue(any("team pace" in note for note in recap.notes))

    def test_improvement_carries_its_place_in_the_match(self) -> None:
        """1.5x her own form can still be far below the median - the text needs both
        numbers to tell a peak from a recovery."""
        entry = recap_service.build_recap(TARGET).improvements[0]
        self.assertEqual(entry.baseline, 9000)
        self.assertEqual(entry.basis_matches, recap_service.IMPROVEMENT_BASIS)
        self.assertEqual(entry.vs_match_median, entry.score - recap_service.build_recap(TARGET).median_score)


class RecordTests(RecapTestCase):
    def test_personal_best_needs_a_history(self) -> None:
        recap = recap_service.build_recap(TARGET)
        names = {entry.name for entry in recap.records}
        self.assertIn("P15", names)
        self.assertIn("P11", names)
        self.assertNotIn("P10", names)

    def test_a_newcomer_sets_no_records(self) -> None:
        """Her first match is her best match - saying so every time is noise."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM matchscore WHERE player_id = 15 AND match_id IN (100, 101)")
        names = {entry.name for entry in recap_service.build_recap(TARGET).records}
        self.assertNotIn("P15", names)


class EventContextTests(RecapTestCase):
    def test_event_matches_carry_the_comparable_sums(self) -> None:
        recap = recap_service.build_recap(TARGET)
        current = [entry for entry in recap.event_matches if entry.is_current]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].match_id, TARGET)
        self.assertEqual(current[0].total_score, sum(FINAL.values()))
        self.assertEqual(recap.position_in_event, recap.matches_in_event)

    def test_season_record_stops_at_this_match(self) -> None:
        recap = recap_service.build_recap(TARGET)
        self.assertEqual(recap.season_matches, len(EARLIER) + 2)  # + the support fixture match
        self.assertEqual(recap.season_wins, len(EARLIER) + 2)

    def test_opponent_history_lists_earlier_meetings(self) -> None:
        recap = recap_service.build_recap(TARGET)
        self.assertEqual([entry.match_id for entry in recap.opponent_history], [1])


class StatusTests(RecapTestCase):
    def test_unknown_match(self) -> None:
        self.assertEqual(recap_service.build_recap(9999).status, "NO_MATCH")

    def test_match_without_results(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM matchscore WHERE match_id = ?", (TARGET,))
        self.assertEqual(recap_service.build_recap(TARGET).status, "NO_SCORES")


class OutputTests(RecapTestCase):
    def test_the_sheet_says_it_is_not_a_post(self) -> None:
        """The whole point of the fact sheet is that somebody writes a text from it.
        Without this line it looks like something to paste into Discord."""
        text = self.capture_stdout(recap_output.print_recap, recap_service.build_recap(TARGET))
        self.assertIn("not a post", text)

    def test_a_rare_podium_is_marked_in_the_output(self) -> None:
        text = self.capture_stdout(recap_output.print_recap, recap_service.build_recap(TARGET))
        self.assertIn("first podium ever", text)
        self.assertIn("no label", text)

    def test_the_output_hands_out_no_epithets(self) -> None:
        """The fact sheet is read by a model writing a public post - a word like
        "regular" leaking into it as a label for a person is what this guards."""
        text = self.capture_stdout(recap_output.print_recap, recap_service.build_recap(TARGET))
        self.assertIn("name the player and the score", text)

    def test_a_newcomer_on_the_podium_is_called_out(self) -> None:
        """A podium in the fourth match is the story; in the four-hundredth it is not."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM matchscore WHERE player_id = 15 AND match_id IN (100, 101)")
        entry = next(e for e in recap_service.build_recap(TARGET).podium if e.name == "P15")
        self.assertEqual(entry.matches_played, 3)
        self.assertTrue(entry.is_newcomer)
        text = self.capture_stdout(recap_output.print_recap, recap_service.build_recap(TARGET))
        self.assertIn("match 4 for this player", text)

    def test_an_established_player_gets_no_newcomer_line(self) -> None:
        """P10 has as many matches as the fixture allows - the line must not appear
        there, or it would show up under every podium."""
        entry = recap_service.build_recap(TARGET).podium[0]
        self.assertEqual(entry.matches_played, len(EARLIER))
        self.assertGreaterEqual(entry.matches_played, recap_service.NEWCOMER_MATCHES)
        self.assertFalse(entry.is_newcomer)

    def test_the_sheet_assigns_no_gender(self) -> None:
        """The roster is mixed and the database records no gender. An English "her" in
        the sheet becomes a German "ihre" in the post - where article, pronoun and
        adjective all carry it - and that is a claim about a real person."""
        text = self.capture_stdout(recap_output.print_recap, recap_service.build_recap(TARGET))
        for word in ("her", "hers", "she", "his", "he", "him"):
            self.assertIsNone(
                re.search(rf"\b{word}\b", text, re.IGNORECASE),
                f"the fact sheet must not say {word!r}",
            )

    def test_json_round_trips(self) -> None:
        import json

        text = self.capture_stdout(recap_output.print_json, recap_service.build_recap(TARGET))
        payload = json.loads(text)
        self.assertEqual(payload["match_id"], TARGET)
        self.assertEqual(len(payload["podium"]), 3)
