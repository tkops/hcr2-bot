from __future__ import annotations

import sqlite3

from hcr2.db import connection
from hcr2.output import broom as broom_output
from hcr2.services import broom as broom_service
from modules import stats as stats_module
from tests.support import TemporaryDatabaseTestCase


class BroomTestCase(TemporaryDatabaseTestCase):
    """A roster of 12 PLTE players over 40 matches, all driving the team average.

    Deviations are then written per test, so every assertion moves exactly one thing.
    """

    ROSTER = 12
    MATCHES = 40
    SEASON = 2                  # das Standardfenster - season 1 ist die Historie
    KM_WEEKS = (2, 3, 4)        # Kilometerwochen innerhalb dieser Saison
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
            # Die Saisonzeilen umspannen genau die Matches, die gleich angelegt werden -
            # sonst liefe der Kilometerzeitraum über Jahre und die km-Tests bewiesen
            # nichts. Saison 3 hat absichtlich kein Match: sie prüft nebenbei, dass
            # current_season() auf die Saison zurückfällt, in der gespielt wird.
            conn.executemany(
                "UPDATE season SET start = ? WHERE number = ?",
                [("2024-01-01", 1), ("2026-01-01", 2)],
            )
            conn.execute(
                "INSERT INTO season (number, name, start, division) VALUES (3, 'Mar 26', '2026-03-01', 'CC')"
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
            # Wochen 2-4 von 2026 - sie liegen in der Saison, die gewertet wird. Broom
            # nimmt die Kilometer des Wertungszeitraums, nicht die letzten N Wochen.
            for player_id in range(100, 100 + self.ROSTER):
                conn.executemany(
                    "INSERT INTO distance (player_id, year, week, km) VALUES (?, 2026, ?, 200)",
                    [(player_id, week) for week in self.KM_WEEKS],
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
        """Driven matches in the *previous* season - raises driven_total without
        adding window rows, which is exactly what a returner looks like. The season
        is what puts them outside the window, so they have to be in another one."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO match (id, teamevent_id, season_number, start, opponent) VALUES (?, 1, 1, ?, 'Alt')",
                [(400 + i, f"2024-01-{1 + i:02d}") for i in range(count)],
            )
            conn.executemany(
                "INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin) VALUES (?, ?, 30000, 100, 0, 0)",
                [(400 + i, player_id) for player_id in player_ids for i in range(count)],
            )

    def _candidate(self, result, player_id: int):
        """Über die Grundmenge, nicht über den Topf: die meisten Tests messen einen
        Faktor, und ob die Spielerin damit in den Topf kommt, ist eine andere Frage."""
        pool = list(result.all_rated) + list(result.immediate_cases)
        return next(c for c in pool if c.player_id == player_id)

    def _shortlisted(self, result, player_id: int) -> bool:
        return any(c.player_id == player_id for c in result.candidates)

    def _factor(self, candidate, key: str):
        return next(f for f in candidate.factors if f.key == key).value


class BroomVetoTests(BroomTestCase):
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
    def test_the_discount_grows_with_tenure_and_is_zero_on_probation(self) -> None:
        limit = broom_service.PROBATION_MATCHES
        self.assertEqual(broom_service.loyalty_discount(1), broom_service.PROBATION_DISCOUNT)
        self.assertEqual(broom_service.loyalty_discount(limit), broom_service.PROBATION_DISCOUNT)
        self.assertEqual(broom_service.loyalty_discount(limit + 1), 0)
        self.assertEqual(broom_service.loyalty_discount(49), 0)
        self.assertEqual(broom_service.loyalty_discount(500), broom_service.LOYALTY_MAX)
        # Monoton: mehr Matches dürfen nie weniger Abzug bedeuten.
        steps = [broom_service.loyalty_discount(n) for n in (49, 149, 299, 499, 500)]
        self.assertEqual(steps, sorted(steps))

    def test_the_discount_is_flat_not_proportional(self) -> None:
        """Der Grund für den Umbau: ein Multiplikator koppelte den Bonus an das
        Rohrisiko, also bekam die Schwächste den größten Schutz - und eine Spielerin
        mit 304 Matches mehr als eine mit 493, weil deren Rohrisiko niedriger war."""
        self._give_history([101, 102], 500)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE distance SET km = 10 WHERE player_id = 101")
        result = broom_service.rank()
        weak = self._candidate(result, 101)
        strong = self._candidate(result, 102)
        self.assertGreater(weak.raw_risk, strong.raw_risk)
        self.assertEqual(weak.loyalty_discount, strong.loyalty_discount)
        self.assertAlmostEqual(
            weak.raw_risk - weak.risk, strong.raw_risk - strong.risk
        )
        # Outside probation the multiplier can only ever lower a risk, so tenure alone
        # never pushes anybody up the list.
        self.assertEqual(max(d for _, d in broom_service.LOYALTY_TIERS), 12)
        self.assertGreater(broom_service.LOYALTY_MAX, 12)
        # Kein Aufschlag mehr: er war fast der einzige Unterschied, seit nur noch
        # Kilometer und Zugehörigkeit reihen, und setzte eine saubere Neue über eine
        # Etablierte mit drei unentschuldigten Fehlterminen.
        self.assertEqual(broom_service.PROBATION_DISCOUNT, 0)

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
        self.assertEqual(candidate.loyalty_discount, 4)
        self.assertLess(candidate.risk, candidate.raw_risk)
        self.assertAlmostEqual(
            candidate.risk, candidate.raw_risk - candidate.loyalty_discount
        )

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
        """'Neu' allein darf niemanden zur Kandidatin machen - der Fehlermodus, gegen
        den der Schutzmultiplikator gebaut ist. Seit nur noch Kilometer und
        Zugehörigkeit reihen, heißt das: nicht *über* einer Etablierten, die
        unentschuldigt gefehlt hat. Gleichauf ist die Folge davon, dass die
        Fehltermine den Eintritt in den Topf bestimmen und nicht die Reihung darin."""
        self._newcomer(101, 6)
        for index in (3, 4, 5):
            self._no_show(102, index)          # an established player with real gaps
        result = broom_service.rank()
        newcomer = self._candidate(result, 101)
        established = self._candidate(result, 102)
        self.assertFalse(newcomer.immediate)
        self.assertLessEqual(newcomer.risk, established.risk)
        self.assertEqual(established.pool_reason, "unexcused")

    def test_a_newcomer_never_moves_anybody_elses_yardstick(self) -> None:
        before = broom_service.rank()
        self._newcomer(101, 3)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE matchscore SET score = 1000 WHERE player_id = 101")
        after = broom_service.rank()
        self.assertAlmostEqual(before.team_unexcused_rate, after.team_unexcused_rate)
        self.assertAlmostEqual(
            self._candidate(before, 103).risk, self._candidate(after, 103).risk
        )

    def test_the_probation_case_leads_the_immediate_tier(self) -> None:
        self._newcomer(101, 6)
        self._no_show(101, self.MATCHES - 1)
        self._newcomer(102, 20)                 # newcomer, past probation
        self._no_show(102, self.MATCHES - 3, checkin=1)
        result = broom_service.rank()
        self.assertTrue(all(c.immediate for c in result.immediate_cases[:2]))
        # Der Probezeitfall führt: gegen ihn gibt es keine Historie abzuwägen, und die
        # Entscheidung ist die billigste auf der Liste.
        self.assertEqual(result.immediate_cases[0].player_id, 101)


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
            broom_service.loyalty_discount(with_bonus.driven_total)
            + broom_service.RETURNER_DISCOUNT
        )
        self.assertEqual(with_bonus.loyalty_discount, expected)
        self.assertGreater(with_bonus.loyalty_discount, 0)
        self.assertAlmostEqual(
            with_bonus.risk, with_bonus.raw_risk - with_bonus.loyalty_discount
        )
        self.assertTrue(any("Rückkehrerin" in reason for reason in with_bonus.reasons))

    def test_an_established_player_is_no_returner_however_long_her_history(self) -> None:
        """Her history is huge too - the gap inside the window is what tells them
        apart, otherwise every veteran would collect the bonus."""
        self._give_history([101], 30)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertGreater(candidate.driven_total, 60)
        self.assertFalse(candidate.returner)
        self.assertEqual(
            candidate.loyalty_discount,
            broom_service.loyalty_discount(candidate.driven_total),
        )

    def test_a_returner_is_never_put_on_probation(self) -> None:
        self._returned(101, window_rows=4, history=20)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertFalse(candidate.probation)
        self.assertGreater(candidate.loyalty_discount, 0)


class BroomRankingTests(BroomTestCase):
    """Im Topf reihen genau zwei Dinge: Kilometer und Zugehörigkeit."""

    def test_four_things_rank_inside_the_pool(self) -> None:
        """Drei gewichtete Achsen plus die Zugehörigkeit als Multiplikator - und
        bewusst nicht mehr, damit ein Rauswurf in einem Satz begründbar bleibt."""
        keys = {factor.key for factor in broom_service.rank().candidates[0].factors}
        self.assertEqual(keys, {"reliability", "performance", "motivation"})
        self.assertNotIn("drops", keys)
        self.assertNotIn("trend", keys)

    def test_unexcused_absence_ranks_and_not_only_admits(self) -> None:
        """Ohne diese Achse wären drei Fehltermine und einer gleichwertig - beide
        kämen nur in den Topf und würden dort nicht mehr unterschieden."""
        self._give_history([101, 102], 40)
        self._no_show(101, 1)
        for index in (1, 2, 5):
            self._no_show(102, index)
        result = broom_service.rank()
        once = self._candidate(result, 101)
        thrice = self._candidate(result, 102)
        self.assertEqual(once.pool_reason, "unexcused")
        self.assertEqual(thrice.pool_reason, "unexcused")
        self.assertLess(
            self._factor(once, "reliability"), self._factor(thrice, "reliability")
        )
        self.assertLess(once.risk, thrice.risk)

    def test_the_reliability_axis_maxes_out_at_the_cap(self) -> None:
        self._give_history([101], 40)
        for index in range(broom_service.UNEXCUSED_CAP + 2):
            self._no_show(101, index)
        self.assertEqual(
            self._factor(self._candidate(broom_service.rank(), 101), "reliability"), 1.0
        )

    def test_performance_ranks_at_equal_kilometres(self) -> None:
        """Der Grund, warum die Leistung wieder mitreiht: bei gleichen Kilometern muss
        die Schwächere oben stehen, sonst reihte der Topf nur nach Kilometern."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE matchscore SET score = ? WHERE player_id = 101",
                (self.BASE_SCORE - 12000,),
            )
        result = broom_service.rank()
        weak = self._candidate(result, 101)
        rest = self._candidate(result, 102)
        self.assertEqual(weak.km_average, rest.km_average)
        self.assertGreater(
            self._factor(weak, "performance"), self._factor(rest, "performance")
        )
        self.assertGreater(weak.risk, rest.risk)

    def test_fewer_kilometres_rank_worse(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE distance SET km = 20 WHERE player_id = 101")
            conn.execute("UPDATE distance SET km = 900 WHERE player_id = 102")
        result = broom_service.rank()
        order = [c.player_id for c in result.candidates]
        self.assertLess(order.index(101), order.index(102))

    def test_tenure_can_only_lower_the_risk_outside_probation(self) -> None:
        """Zwei gleiche Kilometerwerte, verschieden lange dabei - der Schutz entscheidet."""
        self._give_history([101], 400)
        result = broom_service.rank()
        veteran = self._candidate(result, 101)
        rookie = self._candidate(result, 102)
        self.assertGreater(veteran.loyalty_discount, 0)
        self.assertEqual(rookie.loyalty_discount, 0)
        self.assertAlmostEqual(veteran.raw_risk, rookie.raw_risk)
        self.assertLess(veteran.risk, rookie.risk)

    def test_a_single_kilometre_week_is_enough_to_rank(self) -> None:
        """In einer laufenden Saison ist eine Woche oft die einzige - die beste
        vorhandene Zahl schlägt gar keine, und der Kopf nennt die Wochenzahl dazu."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance WHERE week > ?", (self.KM_WEEKS[0],))
            conn.execute("UPDATE distance SET km = 20 WHERE player_id = 101")
        result = broom_service.rank()
        self.assertEqual(result.km_weeks, 1)
        self.assertIsNotNone(self._factor(self._candidate(result, 101), "motivation"))

    def test_without_kilometres_the_other_two_axes_carry_the_ranking(self) -> None:
        """Ihr Gewicht wird umgelegt - ein Sonderweg ist dafür nicht nötig, und die
        Ausgabe sagt, dass eine der drei Achsen fehlt."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance")
            conn.execute(
                "UPDATE matchscore SET score = ? WHERE player_id = 101",
                (self.BASE_SCORE - 9000,),
            )
        result = broom_service.rank()
        self.assertEqual(result.km_weeks, 0)
        self.assertEqual(result.candidates[0].player_id, 101)
        self.assertIsNone(self._factor(result.candidates[0], "motivation"))
        text = self.capture_stdout(broom_output.print_result, result)
        self.assertIn("Keine Kilometer im Zeitraum", text)


class BroomShrinkageTests(BroomTestCase):
    def test_a_thin_window_is_still_rated(self) -> None:
        """Everybody in the team gets judged - eine dünne Stichprobe ist ein Grund,
        genauer hinzusehen, kein Grund, jemanden gar nicht erst zu bewerten."""
        self._give_history([101], 15)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 101 AND match_id BETWEEN 205 AND 299"
            )
        result = broom_service.rank()
        candidate = self._candidate(result, 101)

        self.assertEqual(candidate.window_driven, 5)
        self.assertEqual(result.unrated, [])
        self.assertIsNotNone(self._factor(candidate, "motivation"))
        # ... and she is not part of the cohort her own factors are measured against.
        self.assertEqual(result.cohort_size, self.ROSTER - 1)


class BroomShortlistTests(BroomTestCase):
    """Zwei Stufen: der Topf ist die Leistung, die Reihung darin ist alles andere."""

    def test_the_target_follows_the_roster_size(self) -> None:
        """Es sollen immer TARGET_FREE_SLOTS Plätze frei werden - fehlen schon Leute,
        müssen entsprechend weniger gehen."""
        result = broom_service.rank()
        expected = max(
            0,
            result.roster_size
            - (broom_service.TEAM_CAPACITY - broom_service.TARGET_FREE_SLOTS),
        )
        self.assertEqual(result.slots_to_free, expected)

    def test_a_full_roster_frees_exactly_the_target(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO players (id, name, garage_power, active, team, is_leader) "
                "VALUES (?, ?, 12000, 1, 'PLTE', 0)",
                [(300 + i, f"F{i:02d}") for i in range(broom_service.TEAM_CAPACITY - self.ROSTER)],
            )
        result = broom_service.rank()
        self.assertEqual(result.roster_size, broom_service.TEAM_CAPACITY)
        self.assertEqual(result.slots_to_free, broom_service.TARGET_FREE_SLOTS)

    def test_the_weakest_driver_can_end_up_last_in_the_pool(self) -> None:
        """Der Kern der zweiten Stufe: im Topf entscheidet nicht mehr die Leistung.
        Eine treue, zuverlässige Spielerin steht trotz Platz 1 der Schwächsten unten."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE matchscore SET score = ? WHERE player_id = 101",
                (self.BASE_SCORE - 12000,),
            )
        self._give_history([101], 400)          # lange dabei -> voller Schutz
        self._no_show(102, 3)                   # eine andere im Topf fehlt unentschuldigt
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE matchscore SET score = ? WHERE player_id = 102 AND score > 0",
                (self.BASE_SCORE - 8000,),
            )
        result = broom_service.rank()
        weakest = self._candidate(result, 101)
        self.assertEqual(weakest.performance_rank, 1)
        order = [c.player_id for c in result.candidates]
        self.assertLess(order.index(102), order.index(101))


class BroomSeasonWindowTests(BroomTestCase):
    """Der Zeitraum ist die Saison - das ist die Einheit, in der entschieden wird.

    Am Saisonende verabschiedet sich die Leitung von einer Handvoll Spielerinnen, und
    Belege aus der Saison davor gehören nicht in diese Entscheidung.
    """

    def _previous_season_matches(self, count: int) -> None:
        """Matches in Saison 1 - dieselbe Historie, die der Kader vorher gefahren ist."""
        self._give_history(list(range(100, 100 + self.ROSTER)), count)

    def test_the_default_window_is_the_current_season(self) -> None:
        self._previous_season_matches(12)
        result = broom_service.rank()
        self.assertEqual(result.season, self.SEASON)
        self.assertEqual(result.matches, self.MATCHES)

    def _short_season(self, length: int, history: int) -> None:
        """Eine kurze laufende Saison neben einer längeren Vorsaison - genau die Lage,
        in der ein fester Matchzähler über die Saisongrenze greifen würde."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM matchscore WHERE match_id >= ?", (200 + length,))
            conn.execute("DELETE FROM match WHERE id >= ?", (200 + length,))
        self._previous_season_matches(history)

    def test_an_earlier_season_does_not_leak_into_the_window(self) -> None:
        """Ein unentschuldigtes Fehlen der Vorsaison darf heute nichts mehr wiegen -
        mit einem festen Matchzähler täte es das, sobald die Saison kürzer ist."""
        self._short_season(length=15, history=25)
        clean = self._candidate(broom_service.rank(), 101).unexcused
        self._write(
            "UPDATE matchscore SET score = 0, points = 0, absent = 0, checkin = 0 "
            "WHERE player_id = ? AND match_id = ?",
            (101, 400),
        )
        self.assertEqual(self._candidate(broom_service.rank(), 101).unexcused, clean)
        # Dieselbe Zeile über ein 40er-Fenster: die Vorsaison ist wieder drin, und der
        # Faktor bewegt sich - so war es vorher, und so ist es jetzt nur noch auf Ansage.
        crossing = broom_service.rank(window=40)
        self.assertEqual(crossing.matches, 40)
        self.assertGreater(self._candidate(crossing, 101).unexcused, clean)

    def test_a_named_season_is_read_instead_of_the_current_one(self) -> None:
        self._previous_season_matches(12)
        result = broom_service.rank(season=1)
        self.assertEqual(result.season, 1)
        self.assertEqual(result.matches, 12)

    def test_last_overrides_the_season_and_crosses_its_boundary(self) -> None:
        """--last ist die ausdrückliche saisonübergreifende Sicht, also gewinnt sie."""
        self._previous_season_matches(12)
        result = broom_service.rank(window=self.MATCHES + 5)
        self.assertIsNone(result.season)
        self.assertEqual(result.matches, self.MATCHES + 5)

    def test_the_window_follows_the_season_length_not_the_default(self) -> None:
        """``is_returner`` misst gegen die Fenstergröße - die muss die echte sein,
        sonst hinge die Erkennung an einer Zahl, die das Fenster gar nicht hat."""
        self._short_season(length=15, history=0)
        result = broom_service.rank()
        self.assertEqual(result.window, 15)
        self.assertEqual(result.matches, 15)

    def test_kilometres_come_from_the_season_not_from_the_last_weeks(self) -> None:
        """Der Motivationsfaktor ist an denselben Zeitraum gebunden wie alles andere -
        Wochen aus der Vorsaison dürfen eine schwache Saison nicht aufhübschen."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance WHERE player_id = 101")
            # Ein starker Wert, aber aus einer Woche vor dieser Saison.
            conn.execute(
                "INSERT INTO distance (player_id, year, week, km) VALUES (101, 2025, 50, 900)"
            )
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
        self.assertIsNone(self._factor(candidate, "motivation"))
        self.assertEqual(candidate.km_weeks, 0)
        # Und der Teamschnitt darf die fremde Woche ebenso wenig sehen.
        self.assertAlmostEqual(result.team_km_average, 200.0)

    def test_only_the_weeks_inside_the_window_are_averaged(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO distance (player_id, year, week, km) VALUES (101, 2026, 20, 800)"
            )
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertEqual(candidate.km_weeks, len(self.KM_WEEKS))
        self.assertAlmostEqual(candidate.km_average, 200.0)

    def test_the_week_count_is_what_was_read_not_how_wide_the_window_is(self) -> None:
        """Die Truhe wird nicht jede Woche gelesen - "aus 4 Wochen" wäre sonst eine
        Behauptung über Daten, die niemand eingetragen hat."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance WHERE week > ?", (self.KM_WEEKS[0],))
        result = broom_service.rank()
        self.assertEqual(result.km_weeks, 1)
        self.assertIn("aus 1 Woche", self.capture_stdout(broom_output.print_result, result))

    def test_a_window_without_any_kilometre_week_says_so(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance")
        text = self.capture_stdout(broom_output.print_result, broom_service.rank())
        self.assertIn("keine Kilometer im Zeitraum", text)

    def test_a_season_without_matches_is_reported_not_crashed(self) -> None:
        result = broom_service.rank(season=99)
        self.assertEqual(result.status, "NO_MATCHES")
        text = self.capture_stdout(broom_output.print_result, result)
        self.assertIn("Saison 99", text)

    def test_season_and_last_together_are_refused_instead_of_one_winning(self) -> None:
        """Sonst gewönne still einer von beiden, und welcher, stünde nur im Kopf."""
        text = self.capture_stdout(
            stats_module.handle_command, "broom", ["--season", "1", "--last", "40"]
        )
        self.assertIn("❌", text)
        self.assertNotIn("🧹 Besen", text)

    def test_the_header_names_the_season_it_was_computed_from(self) -> None:
        """Eine Rangliste ohne ihren Zeitraum ist nicht überprüfbar."""
        season = self.capture_stdout(broom_output.print_result, broom_service.rank())
        self.assertIn(f"Saison {self.SEASON} ({self.MATCHES} Matches)", season)
        window = self.capture_stdout(
            broom_output.print_result, broom_service.rank(window=10)
        )
        self.assertIn("letzte 10 Matches", window)


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

    def test_garage_power_plays_no_part_at_all(self) -> None:
        """Für einen freien Platz zählt, was eine Spielerin einfährt - nicht, ob ihre
        Ausrüstung mehr hergegeben hätte. Zwei gleiche Ergebnisse, weit
        auseinanderliegende Garagen: die Bewertung darf sich nicht unterscheiden."""
        with sqlite3.connect(self.db_path) as conn:
            for index in range(10):
                power = 9000 + index * 600
                conn.execute("UPDATE players SET garage_power = ? WHERE id = ?", (power, 100 + index))
                conn.execute(
                    "UPDATE matchscore SET score = ? WHERE player_id = ?",
                    (self.BASE_SCORE + (power - 12000), 100 + index),
                )
            conn.execute("UPDATE players SET garage_power = 9600 WHERE id = 110")
            conn.execute("UPDATE players SET garage_power = 14400 WHERE id = 111")
            conn.execute(
                "UPDATE matchscore SET score = ? WHERE player_id IN (110, 111)",
                (self.BASE_SCORE,),
            )
        result = broom_service.rank()
        small = self._candidate(result, 110)
        large = self._candidate(result, 111)
        self.assertAlmostEqual(small.raw_delta, large.raw_delta, places=6)
        self.assertAlmostEqual(small.risk, large.risk, places=6)
        self.assertFalse(hasattr(result, "gp_slope"))

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
        self.assertEqual(sum(weight for _, _, weight, _ in broom_service.FACTORS), 100)
        self.assertTrue(all(explanation and icon for *_, explanation, icon in broom_service.FACTORS))

    def test_one_unexcused_absence_is_an_unconditional_ticket(self) -> None:
        """Vorgabe der Teamleitung: nicht zu erscheinen ist der eine Fehler, über den
        nicht verhandelt wird - auch nicht bei einer überdurchschnittlichen Fahrerin."""
        with sqlite3.connect(self.db_path) as conn:
            # P01 fährt deutlich über dem Feld und fehlt genau einmal.
            conn.execute(
                "UPDATE matchscore SET score = ? WHERE player_id = 101",
                (self.BASE_SCORE + 9000,),
            )
        self._give_history([101], 40)           # keine Probezeit, kein Sofortfall
        self._no_show(101, 3)
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
        self.assertFalse(candidate.immediate)
        self.assertGreater(candidate.raw_delta, 0)      # fährt über dem Median
        self.assertTrue(self._shortlisted(result, 101))
        self.assertEqual(candidate.pool_reason, "unexcused")

    def test_the_pool_may_outgrow_the_target_size(self) -> None:
        """SHORTLIST_SIZE ist die Zielgröße fürs Auffüllen, keine Obergrenze für die
        Fehltermine - "einmal gefehlt kommt rein" ist bedingungslos."""
        self._give_history(list(range(100, 100 + self.ROSTER)), 40)
        for offset, player_id in enumerate(range(101, 100 + self.ROSTER)):
            self._no_show(player_id, offset)
        result = broom_service.rank()
        by_absence = [c for c in result.candidates if c.pool_reason == "unexcused"]
        self.assertEqual(len(by_absence), self.ROSTER - 1)
        self.assertGreater(len(result.candidates), broom_service.SHORTLIST_SIZE)

    def test_the_rest_is_filled_up_by_performance(self) -> None:
        result = broom_service.rank()
        reasons = {c.pool_reason for c in result.candidates}
        self.assertEqual(reasons, {"performance"})      # niemand fehlt unentschuldigt
        self.assertEqual(len(result.candidates), broom_service.SHORTLIST_SIZE)
        ranks = [c.performance_rank for c in result.candidates]
        self.assertEqual(sorted(ranks), list(range(1, broom_service.SHORTLIST_SIZE + 1)))

    def test_a_player_who_never_drove_leads_the_shortlist(self) -> None:
        """Ohne eine gefahrene Zeile gibt es keinen Abstand zum Median - sie hat dem
        Team nichts eingebracht, und genau das füllt den Topf."""
        self._give_history([101], 20)           # keine Probezeit, also kein Sofortfall
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE matchscore SET score = 0, points = 0 "
                "WHERE player_id = 101 AND match_id BETWEEN 200 AND 299"
            )
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
        self.assertIsNone(candidate.raw_delta)
        self.assertFalse(candidate.immediate)
        self.assertEqual(candidate.performance_rank, 1)
        self.assertTrue(self._shortlisted(result, 101))

    def test_being_signed_off_all_season_does_not_head_the_shortlist(self) -> None:
        """Entschuldigtes Fehlen ist im ganzen Modell kein Vorwurf - über die
        Topfauswahl würde es sonst doch einer, und zwar der schwerste von allen."""
        self._give_history([101], 20)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE matchscore SET score = 0, points = 0, absent = 1 "
                "WHERE player_id = 101 AND match_id BETWEEN 200 AND 299"
            )
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
        self.assertIsNone(candidate.raw_delta)
        self.assertEqual(candidate.excused, self.MATCHES)
        self.assertFalse(self._shortlisted(result, 101))

    def test_the_shortlist_holds_exactly_the_weakest(self) -> None:
        result = broom_service.rank()
        self.assertEqual(len(result.candidates), broom_service.SHORTLIST_SIZE)
        ranks = sorted(c.performance_rank for c in result.candidates)
        self.assertEqual(ranks, sorted(ranks))
        # Niemand außerhalb des Topfes fährt schwächer als die Schwächste darin.
        outside = [c for c in result.all_rated if not self._shortlisted(result, c.player_id)]
        self.assertTrue(all(c.performance_rank > max(ranks) for c in outside))

    def test_the_shortlist_entry_names_the_distance_to_the_median(self) -> None:
        """Die Zahl, die sie in den Topf gebracht hat, muss in ihrer Begründung stehen -
        sonst steht ein Name da, den niemand einordnen kann."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE matchscore SET score = ? WHERE player_id = 101",
                (self.BASE_SCORE - 9000,),
            )
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertTrue(self._shortlisted(broom_service.rank(), 101))
        self.assertTrue(any("zum Match-Median" in reason for reason in candidate.reasons))

    def test_leaders_are_skipped_but_still_set_the_yardstick(self) -> None:
        with_leaders = broom_service.rank(include_leaders=True)
        without = broom_service.rank()
        self.assertNotIn(100, [c.player_id for c in without.candidates])
        self.assertIn(100, [c.player_id for c in with_leaders.candidates])
        self.assertEqual(without.leaders_skipped, 1)
        self.assertNotIn(100, [u.player_id for u in without.unrated])
        # Same yardstick either way: the cohort statistics cover the whole roster.
        self.assertAlmostEqual(
            without.team_unexcused_rate, with_leaders.team_unexcused_rate
        )
        self.assertAlmostEqual(
            self._candidate(without, 101).risk, self._candidate(with_leaders, 101).risk
        )


class BroomOutputTests(BroomTestCase):
    def test_an_immediate_case_is_printed_outside_the_pool(self) -> None:
        """Über einen Sofortfall wird nicht abgewogen, er steht also nicht im Topf -
        aber er wird gezeigt, weil sein Platz auf die zu schaffenden zählt."""
        self._no_show(101, 3)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 101 AND match_id > ?",
                (200 + broom_service.PROBATION_MATCHES,),
            )
        result = broom_service.rank()
        self.assertIn(101, [c.player_id for c in result.immediate_cases])
        self.assertFalse(self._shortlisted(result, 101))
        text = self.capture_stdout(broom_output.print_result, result)
        self.assertIn("Sofortfälle", text)
        self.assertIn("Sofortfall", text)

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
        self.assertIn("Gereiht wird darin nach vier Dingen", text)
        # Die Legende ist handgeschrieben, damit jede Zeile sagen kann, welche echte
        # Zahl in ihrer Spalte steht - also wird geprüft, dass keine Achse fehlt.
        for _, label, weight, _ in broom_service.FACTORS:
            self.assertIn(f"{label:<8}{weight:>2}", text)
        self.assertIn("die Spalten zeigen die echten Werte", text)
        self.assertIn(broom_service.LOYALTY_LABEL, text)
        self.assertIn("Entschuldigtes Fehlen zählt nirgends", text)
        # Die Zugehörigkeit reiht mit, steht aber nicht in FACTORS - sie ist der
        # Multiplikator. Fehlt sie in der Legende, sind es nur noch "zwei Dinge" im Text.
        self.assertIn("Zugehörigkeit", text)

    def test_the_table_shows_real_values_not_percentiles(self) -> None:
        """Mit einer 87 kann im Gespräch niemand etwas anfangen - -23.2k, 820 km,
        2 Fehltermine und 776 Matches schon."""
        result = broom_service.rank()
        candidate = result.candidates[0]
        row = " ".join(broom_output._row(candidate, 1))
        self.assertIn(f"{candidate.raw_delta / 1000:+.1f}k", row)
        self.assertIn(str(candidate.km_total), row)
        self.assertIn(str(candidate.driven_total), row)
        # Der Abzug selbst steht nicht in der Zeile, nur die Matchzahl dahinter.
        self.assertNotIn("x0.", row)

    def test_the_performance_column_matches_stats_perf(self) -> None:
        """Dieselbe Zahl wie 'stats perf --driven-only' - sonst hätte das Team zwei
        Wahrheiten über dieselbe Spielerin."""
        from modules import stats as stats_module

        result = broom_service.rank()
        text = self.capture_stdout(
            stats_module.handle_command, "perf", [str(self.SEASON), "--driven-only"]
        )
        for candidate in result.candidates:
            if candidate.raw_delta is None:
                continue
            self.assertIn(
                f"{candidate.raw_delta / 1000:.1f}k".replace("-0.0k", "0.0k"), text
            )

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

    def test_no_emoji_in_the_table_header(self) -> None:
        """Ein Emoji ist zwei Anzeigespalten breit, für ``len()`` aber ein Zeichen, und
        rendert je nach Discord-Client unterschiedlich - eine Tabelle, die nur manchmal
        ausgerichtet ist, ist schlechter als eine ohne Symbole. Die Spaltenköpfe sind
        deshalb Wörter, die außerdem gleich sagen, was in der Spalte steht."""
        labels = [label for _, label, _, _ in broom_service.FACTORS]
        labels.append(broom_service.LOYALTY_LABEL)
        for label in labels:
            self.assertTrue(label.isascii(), label)
            self.assertTrue(label.replace(" ", "").isalnum(), label)
        text = self.capture_stdout(broom_output.print_result, broom_service.rank())
        header = next(line for line in text.splitlines() if "Spielerin" in line)
        self.assertTrue(header.isascii(), header)

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
        self.assertEqual(self._factor(candidate, "motivation"), 0.5)

    def test_every_candidate_names_the_kilometres_that_ranked_her(self) -> None:
        """Ein Name mit leerem Block darunter liest sich als Fehler - und eine
        Begründung, die das Reihungskriterium verschweigt, taugt für kein Gespräch.
        Deshalb stehen die Kilometer immer da, nicht erst unter einer Schwelle."""
        for candidate in broom_service.rank().candidates:
            self.assertTrue(candidate.reasons)
            self.assertTrue(
                any("km im Zeitraum" in reason for reason in candidate.reasons),
                candidate.reasons,
            )

    def test_without_kilometre_data_the_block_says_so(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance")
        for candidate in broom_service.rank().candidates:
            self.assertIn("keine Kilometer im Zeitraum gemeldet", candidate.reasons)

    def test_a_window_without_a_cohort_says_so_instead_of_looking_solid(self) -> None:
        """MIN_MATCHES no longer gates who is judged, only who sets the yardstick - so
        a short window still produces a ranking, and it has to admit what it is."""
        # Ein Fenster, in dem niemand die (fensterabhängige) Schwelle erreicht: alle
        # fahren nur das älteste Match des Fensters.
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE matchscore SET score = 0, points = 0, absent = 1 "
                "WHERE match_id BETWEEN ? AND ?",
                (200 + self.MATCHES - 4, 200 + self.MATCHES - 1),
            )
        result = broom_service.rank(window=5)
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
