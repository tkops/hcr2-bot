from __future__ import annotations

import sqlite3

from hcr2.db import connection
from hcr2.output import broom as broom_output
from hcr2.services import broom as broom_service
from tests.support import TemporaryDatabaseTestCase


class BroomTestCase(TemporaryDatabaseTestCase):
    """A roster of 12 PLTE players over 40 matches, all driving the team average.

    Deviations are then written per test, so every assertion moves exactly one thing.
    """

    ROSTER = 12
    MATCHES = 40
    BASE_SCORE = 30000

    def setUp(self) -> None:
        super().setUp()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM matchscore")
            conn.execute("DELETE FROM match")
            conn.execute("UPDATE players SET active = 0, team = 'PL1' WHERE id IN (1, 2)")
            conn.executemany(
                "INSERT INTO players (id, name, garage_power, active, team, is_leader) VALUES (?, ?, ?, 1, 'PLTE', ?)",
                [(100 + i, f"P{i:02d}", 12000, 1 if i == 0 else 0) for i in range(self.ROSTER)],
            )
            conn.executemany(
                "INSERT INTO match (id, teamevent_id, season_number, start, opponent) VALUES (?, 1, 2, ?, 'Rivals')",
                [(200 + i, f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}") for i in range(self.MATCHES)],
            )
            conn.executemany(
                "INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin) VALUES (?, ?, ?, 100, 0, 0)",
                [
                    (200 + m, 100 + p, self.BASE_SCORE)
                    for m in range(self.MATCHES)
                    for p in range(self.ROSTER)
                ],
            )
            for player_id in range(100, 100 + self.ROSTER):
                conn.executemany(
                    "INSERT INTO distance (player_id, year, week, km) VALUES (?, 2026, ?, 200)",
                    [(player_id, week) for week in (30, 31, 32)],
                )

    # --- helpers ----------------------------------------------------------

    def _write(self, sql: str, params: tuple) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(sql, params)

    def _no_show(self, player_id: int, match_index: int, *, absent: int = 0, checkin: int = 0) -> None:
        self._write(
            "UPDATE matchscore SET score = 0, points = 0, absent = ?, checkin = ? WHERE match_id = ? AND player_id = ?",
            (absent, checkin, 200 + match_index, player_id),
        )

    def _give_history(self, player_ids, count: int) -> None:
        """Driven matches outside the window - raises driven_total without adding
        window rows, which is exactly what a returner looks like."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO match (id, teamevent_id, season_number, start, opponent) VALUES (?, 1, 2, ?, 'Alt')",
                [(400 + i, f"2024-01-{1 + i:02d}") for i in range(count)],
            )
            conn.executemany(
                "INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin) VALUES (?, ?, 30000, 100, 0, 0)",
                [(400 + i, player_id) for player_id in player_ids for i in range(count)],
            )

    def _candidate(self, result, player_id: int):
        return next(c for c in result.candidates if c.player_id == player_id)

    def _factor(self, candidate, key: str):
        return next(f for f in candidate.factors if f.key == key).value


class BroomVetoTests(BroomTestCase):
    def test_repeated_episodes_max_out_reliability_without_vetoing_a_veteran(self) -> None:
        """A veteran who carries the team in points is not removed over two of these,
        so the axis maxes out and the rest of the model still gets to speak."""
        self._no_show(101, 5, checkin=1)
        self._no_show(101, 20, checkin=1)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertEqual(candidate.blocker_episodes, broom_service.BLOCKER_FLOOR_EPISODES)
        self.assertEqual(self._factor(candidate, "reliability"), 1.0)
        self.assertFalse(candidate.immediate)
        self.assertTrue(any("voll ausgereizt" in reason for reason in candidate.reasons))

    def test_one_episode_vetoes_a_newcomer(self) -> None:
        self._give_history([101], 0)
        with sqlite3.connect(self.db_path) as conn:
            # Below NEWCOMER_MATCHES but past probation.
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 101 AND match_id < ?",
                (200 + self.MATCHES - 15,),
            )
        self._no_show(101, self.MATCHES - 3, checkin=1)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertLess(candidate.driven_total, broom_service.NEWCOMER_MATCHES)
        self.assertFalse(candidate.probation)
        self.assertTrue(candidate.immediate)

    def test_one_checkin_no_show_alone_is_only_weighted(self) -> None:
        self._no_show(101, 5, checkin=1)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertFalse(candidate.immediate)
        self.assertEqual(candidate.blocker_episodes, 1)

    def test_consecutive_matches_are_one_episode_not_two(self) -> None:
        """The real case: a founder had two of these two days apart."""
        self._no_show(101, 5, checkin=1)
        self._no_show(101, 6, checkin=1)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertEqual(candidate.blocker_episodes, 1)
        self.assertFalse(candidate.immediate)

    def test_a_newcomer_is_an_immediate_case_after_one_episode(self) -> None:
        # Only 12 driven matches ever, so below NEWCOMER_MATCHES.
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 101 AND match_id > ?",
                (200 + broom_service.MIN_MATCHES + 1,),
            )
        self._no_show(101, 5, checkin=1)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertLess(candidate.driven_total, broom_service.NEWCOMER_MATCHES)
        self.assertTrue(candidate.immediate)

    def test_earlier_episodes_are_reported_but_never_ranked(self) -> None:
        result_before = broom_service.rank(window=10)
        self._no_show(101, 0, checkin=1)       # oldest matches, outside a 10-match window
        self._no_show(101, 5, checkin=1)
        result = broom_service.rank(window=10)
        candidate = self._candidate(result, 101)
        self.assertEqual(candidate.blockers_earlier, 2)
        self.assertEqual(candidate.blocker_episodes, 0)
        self.assertFalse(candidate.immediate)
        self.assertAlmostEqual(candidate.risk, self._candidate(result_before, 101).risk)


class BroomLoyaltyTests(BroomTestCase):
    def test_loyalty_protects_above_probation_and_accuses_inside_it(self) -> None:
        limit = broom_service.PROBATION_MATCHES
        self.assertEqual(broom_service.loyalty_multiplier(1), broom_service.PROBATION_PENALTY)
        self.assertEqual(broom_service.loyalty_multiplier(limit), broom_service.PROBATION_PENALTY)
        self.assertEqual(broom_service.loyalty_multiplier(limit + 1), 1.0)
        self.assertEqual(broom_service.loyalty_multiplier(49), 1.0)
        self.assertEqual(broom_service.loyalty_multiplier(500), broom_service.LOYALTY_FLOOR)
        # Outside probation the multiplier can only ever lower a risk, so tenure alone
        # never pushes anybody up the list.
        self.assertLessEqual(max(f for _, f in broom_service.LOYALTY_TIERS), 1.0)
        self.assertGreater(broom_service.PROBATION_PENALTY, 1.0)

    def test_the_shield_lowers_the_risk_but_not_the_raw_value(self) -> None:
        # History outside the window still counts toward loyalty - that is the point
        # of measuring it on everything she ever drove.
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO match (id, teamevent_id, season_number, start, opponent) VALUES (?, 1, 2, ?, 'Old')",
                [(300 + i, f"2025-01-{1 + i:02d}") for i in range(20)],
            )
            conn.executemany(
                "INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin) VALUES (?, 101, 30000, 100, 0, 0)",
                [(300 + i,) for i in range(20)],
            )
        self._no_show(101, 3)
        self._no_show(101, 4)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertEqual(candidate.driven_total, 58)
        self.assertEqual(candidate.loyalty, 0.9)
        self.assertLess(candidate.risk, candidate.raw_risk)
        self.assertAlmostEqual(candidate.risk, candidate.raw_risk * candidate.loyalty)

    def test_a_veteran_is_not_pushed_up_by_tenure_alone(self) -> None:
        """Loyalty is a multiplier, so an unremarkable veteran cannot outrank a
        newcomer who behaves identically."""
        result = broom_service.rank()
        risks = {c.player_id: c.risk for c in result.candidates}
        self.assertEqual(len(set(round(value, 6) for value in risks.values())), 1)


class BroomProbationTests(BroomTestCase):
    """The first PROBATION_MATCHES for the team, where nothing is forgiven yet."""

    def _newcomer(self, player_id: int, driven: int) -> None:
        """Strip her back to `driven` matches at the end of the window."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = ? AND match_id < ?",
                (player_id, 200 + self.MATCHES - driven),
            )

    def test_a_newcomer_missing_a_match_is_an_immediate_case(self) -> None:
        """The rule in the leaders' words: whoever ducks out of her first match is out."""
        self._newcomer(101, 6)
        self._no_show(101, self.MATCHES - 1)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertTrue(candidate.probation)
        self.assertTrue(candidate.immediate)
        self.assertTrue(any("Probezeit" in reason for reason in candidate.reasons))

    def test_the_same_absence_is_only_weighted_once_she_is_established(self) -> None:
        self._no_show(101, 3)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertFalse(candidate.probation)
        self.assertFalse(candidate.immediate)

    def test_a_newcomer_is_rated_below_the_minimum_instead_of_deferred(self) -> None:
        """Being new is the reason to look closer, not the reason to wait."""
        self._newcomer(101, 4)
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
        self.assertLess(candidate.window_driven, broom_service.MIN_MATCHES)
        self.assertNotIn(101, [entry.player_id for entry in result.unrated])

    def test_a_clean_newcomer_is_not_pushed_to_the_top(self) -> None:
        """The penalty must not turn 'new' by itself into a candidate - that was the
        failure mode the protective multiplier was built to avoid."""
        self._newcomer(101, 6)
        for index in (3, 4, 5):
            self._no_show(102, index)          # an established player with real gaps
        result = broom_service.rank()
        newcomer = self._candidate(result, 101)
        established = self._candidate(result, 102)
        self.assertFalse(newcomer.immediate)
        self.assertLess(newcomer.risk, established.risk)

    def test_probation_is_measured_without_shrinkage(self) -> None:
        """Same window, same absence - only the history differs. Shrinkage would call
        one absence out of eleven 'about average'; on probation it is what it is."""
        self._newcomer(101, broom_service.MIN_MATCHES + 1)
        self._no_show(101, self.MATCHES - 1)
        on_probation = self._factor(self._candidate(broom_service.rank(), 101), "reliability")

        self._give_history([101], 15)           # same window, now long established
        established = self._factor(self._candidate(broom_service.rank(), 101), "reliability")

        rows = broom_service.MIN_MATCHES + 1
        self.assertAlmostEqual(on_probation, 1 / rows / broom_service.UNEXCUSED_SCALE)
        self.assertLess(established, on_probation)

    def test_a_newcomer_never_moves_anybody_elses_yardstick(self) -> None:
        before = broom_service.rank()
        self._newcomer(101, 3)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE matchscore SET score = 1000 WHERE player_id = 101")
        after = broom_service.rank()
        self.assertAlmostEqual(before.gp_slope, after.gp_slope)
        self.assertAlmostEqual(
            self._candidate(before, 103).risk, self._candidate(after, 103).risk
        )

    def test_the_probation_case_leads_the_immediate_tier(self) -> None:
        self._newcomer(101, 6)
        self._no_show(101, self.MATCHES - 1)
        self._newcomer(102, 20)                 # newcomer, past probation
        self._no_show(102, self.MATCHES - 3, checkin=1)
        result = broom_service.rank()
        self.assertTrue(all(c.immediate for c in result.candidates[:2]))
        self.assertEqual(result.candidates[0].player_id, 101)


class BroomReturnerTests(BroomTestCase):
    """Coming back is loyalty, and a thin window must not read as being new."""

    def _returned(self, player_id: int, *, window_rows: int, history: int) -> None:
        self._give_history([player_id], history)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = ? AND match_id BETWEEN 200 AND 299 AND match_id < ?",
                (player_id, 200 + self.MATCHES - window_rows),
            )

    def test_a_returner_is_told_apart_from_a_newcomer_by_her_history(self) -> None:
        self._returned(101, window_rows=6, history=20)      # left and came back
        self._newcomer_only_window(102, window_rows=6)      # genuinely new
        result = broom_service.rank()

        self.assertTrue(self._candidate(result, 101).returner)
        self.assertFalse(self._candidate(result, 102).returner)

    def _newcomer_only_window(self, player_id: int, *, window_rows: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = ? AND match_id < ?",
                (player_id, 200 + self.MATCHES - window_rows),
            )

    def test_the_returner_bonus_lowers_the_risk(self) -> None:
        self._returned(101, window_rows=6, history=20)
        with_bonus = self._candidate(broom_service.rank(), 101)
        expected = (
            broom_service.loyalty_multiplier(with_bonus.driven_total)
            * broom_service.RETURNER_BONUS
        )
        self.assertAlmostEqual(with_bonus.loyalty, expected)
        self.assertLess(with_bonus.loyalty, 1.0)
        self.assertAlmostEqual(with_bonus.risk, with_bonus.raw_risk * with_bonus.loyalty)
        self.assertTrue(any("Rückkehrerin" in reason for reason in with_bonus.reasons))

    def test_an_established_player_is_no_returner_however_long_her_history(self) -> None:
        """Her history is huge too - the gap inside the window is what tells them
        apart, otherwise every veteran would collect the bonus."""
        self._give_history([101], 30)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertGreater(candidate.driven_total, 60)
        self.assertFalse(candidate.returner)
        self.assertEqual(candidate.loyalty, broom_service.loyalty_multiplier(candidate.driven_total))

    def test_a_returner_is_never_put_on_probation(self) -> None:
        self._returned(101, window_rows=4, history=20)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertFalse(candidate.probation)
        self.assertLess(candidate.loyalty, 1.0)


class BroomShrinkageTests(BroomTestCase):
    def test_a_small_sample_is_pulled_toward_the_team_rate(self) -> None:
        """One absence out of twelve is 8%, and must not beat three out of forty."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM matchscore WHERE player_id = 101 AND match_id > ?", (211,))
        self._no_show(101, 5)                    # 1 of 12
        for index in (3, 4, 6):
            self._no_show(102, index)            # 3 of 40

        result = broom_service.rank()
        newcomer = self._factor(self._candidate(result, 101), "reliability")
        veteran = self._factor(self._candidate(result, 102), "reliability")
        self.assertLess(newcomer, veteran)

    def test_a_thin_window_is_rated_but_keeps_the_noisy_factors_out(self) -> None:
        """Everybody in the team gets judged. The factors that a five-match sample
        cannot carry opt out on their own, and their weight is redistributed."""
        self._give_history([101], 15)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 101 AND match_id BETWEEN 205 AND 299"
            )
        result = broom_service.rank()
        candidate = self._candidate(result, 101)

        self.assertEqual(candidate.window_driven, 5)
        self.assertEqual(result.unrated, [])
        self.assertIsNone(self._factor(candidate, "trend"))
        self.assertIsNone(self._factor(candidate, "drops"))
        self.assertIsNotNone(self._factor(candidate, "reliability"))
        # ... and she is not part of the cohort her own factors are measured against.
        self.assertEqual(result.cohort_size, self.ROSTER - 1)

    def test_trend_and_drops_stay_unrated_below_the_minimum(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 101 AND match_id > ?",
                (200 + broom_service.MIN_MATCHES,),
            )
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertLess(candidate.window_driven, broom_service.MIN_TREND_MATCHES)
        self.assertIsNone(self._factor(candidate, "trend"))
        self.assertIsNone(self._factor(candidate, "drops"))
        # The weight of an unrated factor is redistributed, not counted as zero.
        self.assertGreater(candidate.raw_risk, 0.0)


class BroomFactorTests(BroomTestCase):
    def test_kilometres_rank_the_least_active_worst(self) -> None:
        self._write("UPDATE distance SET km = 20 WHERE player_id = 101", ())
        self._write("UPDATE distance SET km = 900 WHERE player_id = 102", ())
        result = broom_service.rank()
        self.assertGreater(
            self._factor(self._candidate(result, 101), "motivation"),
            self._factor(self._candidate(result, 102), "motivation"),
        )

    def test_without_kilometre_weeks_the_factor_is_unrated(self) -> None:
        self._write("DELETE FROM distance WHERE player_id = 101", ())
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertIsNone(self._factor(candidate, "motivation"))
        self.assertIsNone(candidate.km_average)

    def test_garage_power_shifts_the_expectation_not_the_raw_delta(self) -> None:
        """A weak driver with a small garage is judged more mildly than the same
        result from a big one - the slope comes from the roster itself."""
        with sqlite3.connect(self.db_path) as conn:
            # Ten players carry a clean GP-to-score relation, so the regression has
            # something to find - the slope is measured, never assumed.
            for index in range(10):
                power = 9000 + index * 600
                conn.execute("UPDATE players SET garage_power = ? WHERE id = ?", (power, 100 + index))
                conn.execute(
                    "UPDATE matchscore SET score = ? WHERE player_id = ?",
                    (self.BASE_SCORE + (power - 12000), 100 + index),
                )
            # Two more at the very same score but far apart in garage power.
            conn.execute("UPDATE players SET garage_power = 9600 WHERE id = 110")
            conn.execute("UPDATE players SET garage_power = 14400 WHERE id = 111")
            conn.execute(
                "UPDATE matchscore SET score = ? WHERE player_id IN (110, 111)",
                (self.BASE_SCORE,),
            )
        result = broom_service.rank()
        self.assertGreater(result.gp_slope, 0.5)
        small = self._candidate(result, 110)
        large = self._candidate(result, 111)
        self.assertAlmostEqual(small.raw_delta, large.raw_delta, places=6)
        # Same result on paper, but the smaller garage was expected to deliver less.
        self.assertGreater(small.performance, large.performance)

    def test_excused_absence_changes_no_score_but_is_still_reported(self) -> None:
        """Excused absence correlates with nothing (r = -0.03 against kilometres), so
        it is real life, not a signal - context in the reasons, never a factor."""
        before = self._candidate(broom_service.rank(), 101).risk
        for index in range(6):
            self._no_show(101, index, absent=1)
        candidate = self._candidate(broom_service.rank(), 101)

        self.assertEqual(candidate.excused, 6)
        self.assertEqual(candidate.unexcused, 0)
        self.assertNotIn("away", [factor.key for factor in candidate.factors])
        # Not through the contribution factor either: an excused row is out of the
        # denominator, so signing off costs her nothing at all.
        self.assertAlmostEqual(candidate.risk, before)
        self.assertTrue(any("zählt nicht" in reason for reason in candidate.reasons))

    def test_the_weights_are_normalised_to_a_hundred(self) -> None:
        self.assertEqual(sum(weight for _, _, weight, _, _ in broom_service.FACTORS), 100)
        self.assertTrue(all(explanation and icon for *_, explanation, icon in broom_service.FACTORS))

    def test_driving_well_now_and_then_beats_driving_every_match_badly(self) -> None:
        """The leaders' own example: 1 point per match over a season is worth less to
        the team than a handful of proper drives."""
        with sqlite3.connect(self.db_path) as conn:
            # P01 drives every match for a single point.
            conn.execute("UPDATE matchscore SET points = 1 WHERE player_id = 101")
            # P02 misses most of them but scores properly when she drives.
            conn.execute("UPDATE matchscore SET points = 0, score = 0 WHERE player_id = 102")
            conn.execute(
                "UPDATE matchscore SET points = 250, score = ? WHERE player_id = 102 AND match_id > ?",
                (self.BASE_SCORE, 200 + self.MATCHES - 12),
            )
        result = broom_service.rank()
        every_match = self._candidate(result, 101)
        now_and_then = self._candidate(result, 102)

        self.assertLess(every_match.points_total, now_and_then.points_total)
        self.assertGreater(
            self._factor(every_match, "contribution"),
            self._factor(now_and_then, "contribution"),
        )

    def test_contribution_is_per_match_so_a_late_joiner_is_not_punished(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE matchscore SET points = 100 WHERE player_id IN (101, 102)")
            # P02 only joined for the last twelve matches.
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 102 AND match_id < ?",
                (200 + self.MATCHES - 12,),
            )
        result = broom_service.rank()
        full = self._candidate(result, 101)
        late = self._candidate(result, 102)

        self.assertLess(late.points_total, full.points_total)
        self.assertAlmostEqual(late.points_per_row, full.points_per_row)
        self.assertEqual(
            self._factor(late, "contribution"), self._factor(full, "contribution")
        )

    def test_a_strong_contributor_gets_a_line_in_her_favour(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE matchscore SET points = 1")
            conn.execute("UPDATE matchscore SET points = 280 WHERE player_id = 101")
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertTrue(
            any("trägt überdurchschnittlich" in reason for reason in candidate.reasons)
        )

    def test_too_few_available_matches_leaves_contribution_unrated(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 101 AND match_id < ?",
                (200 + self.MATCHES - (broom_service.MIN_CONTRIBUTION_ROWS - 1),),
            )
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertIsNone(self._factor(candidate, "contribution"))
        self.assertIsNone(candidate.points_per_row)

    def test_leaders_are_skipped_but_still_set_the_yardstick(self) -> None:
        with_leaders = broom_service.rank(include_leaders=True)
        without = broom_service.rank()
        self.assertNotIn(100, [c.player_id for c in without.candidates])
        self.assertIn(100, [c.player_id for c in with_leaders.candidates])
        self.assertEqual(without.leaders_skipped, 1)
        self.assertNotIn(100, [u.player_id for u in without.unrated])
        # Same yardstick either way: the cohort statistics cover the whole roster.
        self.assertAlmostEqual(without.gp_slope, with_leaders.gp_slope)
        self.assertAlmostEqual(
            self._candidate(without, 101).risk, self._candidate(with_leaders, 101).risk
        )


class BroomOutputTests(BroomTestCase):
    def test_an_immediate_case_is_printed_without_a_risk_value(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 101 AND match_id < ?",
                (200 + self.MATCHES - 6,),
            )
        self._no_show(101, self.MATCHES - 1, checkin=1)
        text = self.capture_stdout(broom_output.print_result, broom_service.rank())
        self.assertIn("Sofortfall", text)
        self.assertIn("eingeloggt und nicht gefahren", text)
        head = next(line for line in text.splitlines() if line.startswith(" 1 "))
        self.assertNotIn(".", head.split()[2])

    def test_every_listed_candidate_carries_reasons(self) -> None:
        for index in (3, 4, 5):
            self._no_show(101, index)
        result = broom_service.rank()
        self.assertTrue(all(candidate.reasons for candidate in result.candidates[:5]))
        text = self.capture_stdout(broom_output.print_result, result)
        self.assertIn("unentschuldigt in", text)

    def test_the_output_stays_inside_two_discord_messages(self) -> None:
        """One message is not the bar any more - the reason blocks and the legend do
        not fit and are not supposed to be dropped. Two is, and send_codeblock splits
        on line boundaries, so this is what may not silently grow."""
        max_discord_msg_len = 1990
        result = broom_service.rank()
        text = self.capture_stdout(lambda: broom_output.print_result(result, show_all=True))
        self.assertLess(len(text), 2 * max_discord_msg_len)

        table = text.split("\n\n")[0]
        self.assertLess(len(table), max_discord_msg_len)

    def test_every_factor_is_explained_in_the_output(self) -> None:
        result = broom_service.rank()
        text = self.capture_stdout(lambda: broom_output.print_result(result))
        self.assertIn("Faktoren (100 = schlechtester Wert im Kader)", text)
        for _, label, weight, explanation, icon in broom_service.FACTORS:
            self.assertIn(explanation, text)
            self.assertIn(f"{label} {weight:>2}", text)
        self.assertIn("Entschuldigtes Fehlen zählt nicht", text)

    def test_the_emoji_header_lines_up_with_the_numbers(self) -> None:
        """An emoji is two display columns but one character, so the header is padded
        by hand. Get that wrong and the table only lines up in some clients."""
        import unicodedata

        def display_width(line: str) -> int:
            return sum(
                2 if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) > 0x1F000 else 1
                for ch in line
            )

        result = broom_service.rank()
        lines = self.capture_stdout(lambda: broom_output.print_result(result)).splitlines()
        header = next(index for index, line in enumerate(lines) if line.startswith(" # "))
        widths = {display_width(line) for line in lines[header : header + 4]}
        self.assertEqual(widths, {broom_output.WIDTH})

    def test_every_icon_is_a_single_codepoint_emoji(self) -> None:
        """Variation selectors, ZWJ sequences and skin tones render inconsistently -
        and an icon that is sometimes one column wide breaks the alignment above."""
        icons = [icon for *_, icon in broom_service.FACTORS]
        icons += [broom_service.LOYALTY_ICON, broom_service.IMMEDIATE_ICON]
        for icon in icons:
            self.assertEqual(len(icon), 1, f"{icon!r} is more than one codepoint")
            self.assertNotIn(ord(icon), (0xFE0E, 0xFE0F))
        self.assertEqual(len(set(icons)), len(icons), "icons have to stay distinguishable")

    def test_json_carries_the_factors_for_a_downstream_reader(self) -> None:
        import json

        payload = json.loads(self.capture_stdout(broom_output.print_json, broom_service.rank()))
        self.assertEqual(payload["status"], "OK")
        self.assertEqual(len(payload["candidates"][0]["factors"]), len(broom_service.FACTORS))

    def test_a_flat_cohort_lands_in_the_middle_not_at_the_extreme(self) -> None:
        """Everyone identical means the factor says nothing, so it must not read as
        'worst in the team' for all of them."""
        self.assertEqual(broom_service._percentile(5.0, [5.0] * 6, low_is_worse=True), 0.5)
        self.assertEqual(broom_service._percentile(5.0, [5.0] * 6, low_is_worse=False), 0.5)
        candidate = broom_service.rank().candidates[0]
        self.assertEqual(self._factor(candidate, "performance"), 0.5)

    def test_a_candidate_without_a_stand_out_still_gets_a_line(self) -> None:
        """A name with an empty block below it reads as a bug, so the strongest
        factor is named even when nothing crossed a reporting threshold."""
        result = broom_service.rank()
        candidate = result.candidates[0]
        self.assertEqual(len(candidate.reasons), 1)
        self.assertIn("nichts sticht heraus", candidate.reasons[0])
        self.assertNotIn("Mot ", candidate.reasons[0])

    def test_a_window_without_a_cohort_says_so_instead_of_looking_solid(self) -> None:
        """MIN_MATCHES no longer gates who is judged, only who sets the yardstick - so
        a short window still produces a ranking, and it has to admit what it is."""
        result = broom_service.rank(window=broom_service.MIN_MATCHES - 1)
        self.assertEqual(result.status, "OK")
        self.assertEqual(result.cohort_size, 0)
        text = self.capture_stdout(lambda: broom_output.print_result(result))
        self.assertIn("Vergleichsfaktoren sind unsicher", text)

    def test_a_window_without_any_roster_row_is_reported(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM matchscore")
        result = broom_service.rank()
        self.assertEqual(result.status, "NO_DATA")
        self.assertIn("Keine Kaderzeile", self.capture_stdout(lambda: broom_output.print_result(result)))

    def test_the_unrated_tail_is_capped(self) -> None:
        """Only players with no roster row at all land there - freshly added members
        who have not seen a match yet."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO players (id, name, garage_power, active, team, is_leader) VALUES (?, ?, 12000, 1, 'PLTE', 0)",
                [(150 + i, f"N{i:02d}") for i in range(broom_output.UNRATED_LIMIT + 3)],
            )
        result = broom_service.rank()
        self.assertGreater(len(result.unrated), broom_output.UNRATED_LIMIT)
        self.assertTrue(all(entry.window_driven == 0 for entry in result.unrated))
        text = self.capture_stdout(lambda: broom_output.print_result(result))
        self.assertIn("keine Kaderzeile im Fenster", text)
        self.assertIn("und 3 weitere", text)

    def test_no_matches_is_reported_not_crashed(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM matchscore")
            conn.execute("DELETE FROM match")
            conn.execute("UPDATE players SET active = 0, team = 'PL1' WHERE id IN (1, 2)")
        result = broom_service.rank()
        self.assertEqual(result.status, "NO_MATCHES")
        self.assertIn("Keine Matches", self.capture_stdout(broom_output.print_result, result))


if __name__ == "__main__":
    import unittest

    unittest.main()
