from __future__ import annotations

import json
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
    # Kilometerwochen **innerhalb des 5-Wochen-Fensters**, das am Saisonende hängt.
    # Saison 2 endet am 2026-02-28, das Fenster ist also KW 5-9 von 2026 - die frühere
    # (2, 3, 4) lag in der Saison, aber nicht mehr im Fenster, aus dem broom liest.
    KM_WEEKS = (5, 6, 7)
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
            # Wochen 5-7 von 2026 - sie liegen im Kilometerfenster, das am Ende der
            # gewerteten Saison hängt (KM_WINDOW_WEEKS breit, hier KW 5-9).
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
        adding window rows. The season is what puts them outside the window, so they
        have to be in another one."""
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
        return next(c for c in result.all_rated if c.player_id == player_id)

    def _shortlisted(self, result, player_id: int) -> bool:
        return any(c.player_id == player_id for c in result.candidates)

    def _flat(self, text: str) -> str:
        """Die Ausgabe ohne ihren Zeilenfall.

        Die Erklärungen werden auf die Tabellenbreite umgebrochen, also kann jede
        Phrase mitten im Satz eine Zeilengrenze überqueren. Geprüft wird der Inhalt,
        nicht wo der Umbruch gerade sitzt - sonst scheitert ein Test daran, dass ein
        Wort in einer Schwelle länger geworden ist.
        """
        return " ".join(text.split())

    def _factor(self, candidate, key: str):
        """Die Besenpunkte einer Achse - plus ist schlecht, minus spricht für sie."""
        return next(f for f in candidate.factors if f.key == key).points


class BroomBlockerTests(BroomTestCase):
    """Eingeloggt und nicht gefahren - der belegte Slot.

    Es gibt **keine Veto-Stufe mehr**: früher machte eine Episode aus einer Neuen
    einen Sofortfall, der neben der Rangliste stand. Das brauchte eine zweite Sprache
    auf der Seite, um zu erklären, warum über jemanden nicht mehr abgewogen wird - und
    die Punkte sagen dasselbe. Eine Neue mit belegtem Slot zahlt BLOCKER_POINTS und
    bekommt keinen Treueabzug, steht also von allein oben.
    """

    def test_a_newcomer_with_a_blocked_slot_rises_on_points_alone(self) -> None:
        self._give_history([101], 0)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 101 AND match_id < ?",
                (200 + self.MATCHES - 15,),
            )
        self._no_show(101, self.MATCHES - 3, checkin=1)
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
        self.assertEqual(candidate.blocker_rows, 1)
        # Ein belegter Slot **ist** zugleich ein unentschuldigter Fehltermin: sie war
        # da und ist nicht gefahren. Er steht nur in der Slot-Spalte und kostet dort
        # seinen eigenen flachen Wert - "Fehlt" bleibt leer, sonst sähe ein Vorfall
        # aus wie zwei.
        self.assertEqual(self._factor(candidate, "reliability"), 0)
        self.assertEqual(self._factor(candidate, "blocker"), broom_service.BLOCKER_POINTS)
        self.assertEqual(self._factor(candidate, "loyalty"), 0)
        # Ohne Sonderregel ganz oben: mehr Punkte als jede, der nichts vorgefallen ist.
        clean = [c for c in result.candidates if not c.blocker_rows and not c.unexcused]
        self.assertTrue(all(candidate.besen > c.besen for c in clean), result.candidates)

    def test_one_checkin_no_show_costs_more_than_a_plain_absence(self) -> None:
        self._no_show(101, 5, checkin=1)
        self._no_show(102, 5)
        result = broom_service.rank()
        blocked = self._candidate(result, 101)
        absent = self._candidate(result, 102)
        self.assertEqual(blocked.blocker_rows, 1)
        self.assertEqual(self._factor(blocked, "blocker"), broom_service.BLOCKER_POINTS)
        self.assertEqual(self._factor(blocked, "reliability"), 0)
        # Die, die gar nicht aufgetaucht ist, steht in der anderen Spalte.
        self.assertEqual(
            self._factor(absent, "reliability"), broom_service.UNEXCUSED_POINTS
        )
        self.assertEqual(self._factor(absent, "blocker"), 0)
        self.assertGreater(blocked.besen, absent.besen)

    def test_two_incidents_in_one_weekend_count_twice(self) -> None:
        """Früher wurden Vorfälle innerhalb weniger Tage zu **einer Episode**
        zusammengefasst. Die Regel gab es, damit die Veto-Stufe nicht bei einem
        einzigen Wochenende zuschlägt - die Stufe ist weg, und mit flachen Punkten je
        Spalte kehrte sie sich ins Gegenteil: zwei belegte Slots an einem Wochenende
        hätten weniger gekostet als zwei schlichte Fehltermine. Wer da war und nicht
        gefahren ist, käme billiger weg als wer gar nicht kam."""
        self._no_show(101, 5, checkin=1)
        self._no_show(101, 6, checkin=1)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertEqual(candidate.blocker_rows, 2)
        self.assertEqual(candidate.unexcused, 2)
        self.assertEqual(self._factor(candidate, "reliability"), 0)
        self.assertEqual(
            self._factor(candidate, "blocker"), 2 * broom_service.BLOCKER_POINTS
        )
        # Und teurer als zweimal gar nicht aufgetaucht - das war der Fehlermodus.
        self.assertGreater(
            2 * broom_service.BLOCKER_POINTS, 2 * broom_service.UNEXCUSED_POINTS
        )
        self.assertFalse(hasattr(broom_service, "BLOCKER_EPISODE_DAYS"))

    def test_a_single_incident_never_shows_up_in_both_columns(self) -> None:
        """Wer sich einloggt und nicht fährt, steht in der DB als unentschuldigter
        Fehltermin **und** als Check-in - in einer gemeinsamen Zelle sah das aus wie
        zwei Vorfälle ("1+1"), obwohl es einer ist. Getrennt zählt jede Zeile genau
        einmal, und die beiden Spalten addieren sich trotzdem zur Gesamtzahl."""
        self._no_show(101, 5, checkin=1)        # einmal da, nicht gefahren
        self._no_show(101, 9)                   # einmal gar nicht aufgetaucht
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertEqual(candidate.unexcused, 2)
        self.assertEqual(candidate.blocker_rows, 1)
        plain = self._factor(candidate, "reliability")
        blocked = self._factor(candidate, "blocker")
        self.assertEqual(plain, broom_service.UNEXCUSED_POINTS)
        self.assertEqual(blocked, broom_service.BLOCKER_POINTS)
        # Zusammen genau so viel, wie das Fehlen insgesamt kostet - kein Vorfall
        # doppelt, keiner verschwunden.
        self.assertEqual(
            plain + blocked,
            broom_service.absence_points(candidate.unexcused, candidate.blocker_rows),
        )
        # Und in der Tabelle steht in jeder Spalte die Zahl der Vorfälle, nicht ihre Summe.
        cells = {f.key: f.value for f in candidate.factors}
        self.assertEqual(cells["reliability"], "1")
        self.assertEqual(cells["blocker"], "1")

    def test_a_blocked_slot_does_not_count_when_she_is_signed_off(self) -> None:
        """Wer abgemeldet ist, greift mit dem Einloggen keine Belohnung ab - dann ist
        die Zeile nur eine entschuldigte Abwesenheit. An der echten DB ist der Fall in
        31 Check-in-No-Shows noch nie vorgekommen; ohne die Regel entschiede der Code
        beim ersten Mal falsch."""
        self._no_show(101, 5, checkin=1, absent=1)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertEqual(candidate.blocker_rows, 0)
        self.assertEqual(candidate.excused, 1)
        self.assertEqual(self._factor(candidate, "reliability"), 0)

    def test_earlier_episodes_are_reported_but_never_ranked(self) -> None:
        result_before = broom_service.rank(window=10)
        self._no_show(101, 0, checkin=1)       # oldest matches, outside a 10-match window
        self._no_show(101, 5, checkin=1)
        result = broom_service.rank(window=10)
        candidate = self._candidate(result, 101)
        self.assertEqual(candidate.blockers_earlier, 2)
        self.assertEqual(candidate.blocker_rows, 0)
        self.assertEqual(candidate.besen, self._candidate(result_before, 101).besen)


class BroomLoyaltyTests(BroomTestCase):
    def test_the_discount_grows_with_tenure_and_is_zero_on_probation(self) -> None:
        treue = broom_service.treue_points
        self.assertEqual(treue(1), 0)
        self.assertEqual(treue(10), 0)
        self.assertEqual(treue(14), 0)
        self.assertEqual(treue(15), -1)
        self.assertEqual(treue(500), broom_service.TREUE_MAX)
        # Monoton: mehr Matches dürfen nie weniger Abzug bedeuten.
        steps = [treue(n) for n in (14, 15, 50, 150, 800)]
        self.assertEqual(steps, sorted(steps, reverse=True))

    def test_tenure_never_adds_points_however_new_somebody_is(self) -> None:
        """Die Treueachse ist **immer <= 0**, und das ist der Grund, warum sie beim
        Umbau auf Besenpunkte nicht mitgedreht wurde: gedreht reihte sie identisch,
        aber sie hätte aus Neusein einen Vorwurf gemacht. Im Kader reicht die Spanne
        von 7 bis 797 Matches - als Strafposten stünden die Jüngsten immer oben."""
        for matches in (0, 1, 7, 14, 15, 49, 50, 149, 150, 500, 797):
            self.assertLessEqual(broom_service.treue_points(matches), 0, matches)
        self.assertLessEqual(broom_service.treue_points(0), 0)
        # Und die Punkte hängen allein an der Matchzahl, nicht daran, wie schlecht
        # jemand dasteht - genau das war der Fehler des alten Multiplikators.
        self._give_history([101, 102], 500)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE distance SET km = 10 WHERE player_id = 101")
        result = broom_service.rank()
        weak = self._candidate(result, 101)
        strong = self._candidate(result, 102)
        self.assertGreater(weak.besen, strong.besen)
        self.assertEqual(weak.loyalty_points, strong.loyalty_points)

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
        self.assertEqual(candidate.loyalty_points, -2)
        # Die Zugehörigkeit steckt in der Summe, und zwar als Minus: ohne sie stünde
        # sie zwei Punkte höher.
        axes = {f.key: f.points for f in candidate.factors}
        self.assertEqual(sum(axes.values()), candidate.besen)
        self.assertEqual(axes["loyalty"], -2)

    def test_a_veteran_is_not_pushed_up_by_tenure_alone(self) -> None:
        """Ein unauffälliger Veteran darf nie über einer Neuen stehen, die sich genau
        gleich verhält - die Treue kann ihn nur nach unten ziehen."""
        result = broom_service.rank()
        for candidate in result.candidates:
            self.assertLessEqual(candidate.loyalty_points, 0)
        veteran = max(result.candidates, key=lambda c: c.driven_total)
        newest = min(result.candidates, key=lambda c: c.driven_total)
        self.assertLessEqual(veteran.loyalty_points, newest.loyalty_points)


class BroomProbationTests(BroomTestCase):
    """Die ersten Matches für das Team, wo noch nichts verdient ist."""

    def _newcomer(self, player_id: int, driven: int) -> None:
        """Strip her back to `driven` matches at the end of the window."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = ? AND match_id < ?",
                (player_id, 200 + self.MATCHES - driven),
            )

    def test_a_newcomer_missing_a_match_pays_the_same_as_everybody(self) -> None:
        """Es gibt keine Probezeitregel mehr. Sie kostet dieselben Punkte wie eine
        Etablierte - bekommt aber keinen Treueabzug, und genau daraus entsteht die
        Schärfe, für die vorher eine eigene Regel nötig war."""
        self._newcomer(101, 6)
        self._no_show(101, self.MATCHES - 1)
        self._no_show(102, self.MATCHES - 1)     # Etablierte, gleicher Fehltermin
        result = broom_service.rank()
        newcomer = self._candidate(result, 101)
        established = self._candidate(result, 102)
        self.assertEqual(
            self._factor(newcomer, "reliability"),
            self._factor(established, "reliability"),
        )
        self.assertEqual(self._factor(newcomer, "loyalty"), 0)
        self.assertLess(self._factor(established, "loyalty"), 0)
        self.assertGreater(newcomer.besen, established.besen)
        self.assertFalse(hasattr(broom_service, "PROBATION_MATCHES"))

    def test_a_newcomer_is_rated_below_the_minimum_instead_of_deferred(self) -> None:
        """Being new is the reason to look closer, not the reason to wait."""
        self._newcomer(101, 4)
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
        self.assertLess(candidate.window_driven, broom_service.MIN_MATCHES)
        self.assertNotIn(101, [entry.player_id for entry in result.unrated])

    def test_a_clean_newcomer_is_not_pushed_to_the_top(self) -> None:  # noqa: D401
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
        self.assertLessEqual(newcomer.besen, established.besen)
        self.assertEqual(established.pool_reason, "unexcused")

    def test_a_newcomer_moves_only_the_perf_scale_and_nothing_else(self) -> None:
        """Drei Achsen sind **absolut** und bleiben stehen, egal wer dazukommt: die
        Kilometer, das Fehlen und die Treue haben feste Schwellen.

        Die vierte ist der Preis dafür, dass jeder Perf-Wert von 1 bis 10 genau einmal
        vorkommt: die Skala ist der Topf, also verschiebt jede, die hineinkommt, die
        Punkte aller anderen darin. Das geht nicht anders, und es steht hier, damit es
        eine Entscheidung bleibt und keine Überraschung.
        """
        before = broom_service.rank()
        self._newcomer(101, 3)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE matchscore SET score = 1000 WHERE player_id = 101")
        after = broom_service.rank()
        self.assertAlmostEqual(before.team_unexcused_rate, after.team_unexcused_rate)

        old, new = self._candidate(before, 103), self._candidate(after, 103)
        for key in ("motivation", "reliability", "loyalty"):
            self.assertEqual(self._factor(old, key), self._factor(new, key), key)
        # Die Neue fährt schwächer als alle und drängt sich damit an die Spitze des
        # Topfes - jede andere rückt eine Perf-Stufe nach unten.
        self.assertTrue(self._shortlisted(after, 101))
        self.assertLess(self._factor(new, "performance"), self._factor(old, "performance"))

    def test_there_is_no_veto_tier_left(self) -> None:
        """Weder im Ergebnis noch in der Ausgabe. Eine Stufe, die jemanden aus der
        Abwägung nimmt, braucht eine zweite Sprache auf der Seite, um sich zu
        erklären - und die Punkte sagen dasselbe."""
        self._newcomer(101, 6)
        self._no_show(101, self.MATCHES - 1)
        self._newcomer(102, 20)
        self._no_show(102, self.MATCHES - 3, checkin=1)
        result = broom_service.rank()
        self.assertFalse(hasattr(result, "immediate_cases"))
        self.assertFalse(hasattr(result.candidates[0], "immediate"))
        self.assertFalse(hasattr(broom_service, "NEWCOMER_MATCHES"))
        text = self.capture_stdout(lambda: broom_output.print_result(result))
        self.assertNotIn("Sofortfall", text)
        # Beide stehen trotzdem oben - allein über ihre Punkte.
        top = [c.player_id for c in result.candidates[:2]]
        self.assertEqual(sorted(top), [101, 102])


class BroomTenureTests(BroomTestCase):
    """Die Treueachse hängt allein an der Zahl gefahrener Matches.

    Es gab einmal einen Zusatzabzug für Rückkehrerinnen, erkannt an Historie außerhalb
    des Fensters plus einer Lücke darin. Seit der Wertungszeitraum die Saison ist (5 bis
    15 Matches statt 40), war die Schwelle größer als ihr eigenes Fenster und konnte
    nicht mehr zutreffen - an Saison 65 hätte sie ``window_rows <= -5`` verlangt. Die
    Regel hat in keiner gemessenen Saison je gegriffen und ist weggefallen.
    """

    def _returned(self, player_id: int, *, window_rows: int, history: int) -> None:
        self._give_history([player_id], history)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = ? AND match_id BETWEEN 200 AND 299 AND match_id < ?",
                (player_id, 200 + self.MATCHES - window_rows),
            )

    def test_a_thin_window_gets_no_extra_discount(self) -> None:
        """Wer zurückkommt und wer neu ist, bekommt dieselbe Stufe - entschieden wird
        allein über die Matchzahl, und die trennt die beiden ohnehin."""
        self._returned(101, window_rows=6, history=20)       # weg gewesen, zurück
        with sqlite3.connect(self.db_path) as conn:          # wirklich neu
            conn.execute(
                "DELETE FROM matchscore WHERE player_id = 102 AND match_id < ?",
                (200 + self.MATCHES - 6,),
            )
        result = broom_service.rank()
        back = self._candidate(result, 101)
        fresh = self._candidate(result, 102)
        self.assertEqual(
            back.loyalty_points, broom_service.treue_points(back.driven_total)
        )
        self.assertEqual(
            fresh.loyalty_points, broom_service.treue_points(fresh.driven_total)
        )
        # Die Historie trennt sie trotzdem: die Rückkehrerin hat mehr Matches und
        # bekommt darüber den größeren Abzug.
        self.assertGreater(back.driven_total, fresh.driven_total)
        self.assertLess(back.loyalty_points, fresh.loyalty_points)

    def test_the_returner_rule_is_gone_for_good(self) -> None:
        self.assertFalse(hasattr(broom_service, "RETURNER_BONUS"))
        self.assertFalse(hasattr(broom_service, "is_returner"))
        result = broom_service.rank()
        self.assertFalse(hasattr(result.candidates[0], "returner"))
        text = self.capture_stdout(lambda: broom_output.print_result(result))
        self.assertNotIn("Rückkehr", text)

    def test_tenure_depends_on_nothing_but_the_match_count(self) -> None:
        """Zwei Ladys mit derselben Matchzahl, aber völlig verschiedener Historie im
        Fenster, bekommen denselben Abzug."""
        self._returned(101, window_rows=4, history=20)
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertEqual(
            candidate.loyalty_points, broom_service.treue_points(candidate.driven_total)
        )
        self.assertLessEqual(candidate.loyalty_points, 0)


class BroomRankingTests(BroomTestCase):
    """Im Topf reihen genau zwei Dinge: Kilometer und Zugehörigkeit."""

    def test_the_axes_add_up_to_the_score(self) -> None:
        """Die Summe **muss** die Zahl in der Tabelle sein: das ist der ganze Zweck der
        Besenpunkte. Wer die Spalten zusammenzählt und etwas anderes herausbekommt als
        die Gesamtzahl, kann nicht mehr nachrechnen."""
        for candidate in broom_service.rank().candidates:
            keys = {factor.key for factor in candidate.factors}
            self.assertEqual(
                keys,
                {"reliability", "blocker", "performance", "motivation", "loyalty"},
            )
            self.assertEqual(
                sum(factor.points for factor in candidate.factors), candidate.besen
            )
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
        self.assertLess(once.besen, thrice.besen)

    def test_every_absence_counts_again_without_a_cap(self) -> None:
        """Kein Deckel mehr: dreimal unentschuldigt wiegt dreifach. Der alte Cap war
        nötig, solange die Achse auf 0..1 normiert war - eine Punktzahl braucht ihn
        nicht und wird ohne ihn erst recht nachrechenbar."""
        self._give_history([101], 40)
        service = broom_service
        self.assertFalse(hasattr(service, "UNEXCUSED_CAP"))
        for count in range(1, 5):
            self.assertEqual(
                service.absence_points(count, 0), count * service.UNEXCUSED_POINTS
            )
        # Der belegte Slot wiegt schwerer als das schlichte Fernbleiben: wer sich
        # einloggt, hatte nachweislich Zeit und greift die Belohnung ab.
        self.assertGreater(service.BLOCKER_POINTS, service.UNEXCUSED_POINTS)
        self.assertEqual(service.absence_points(1, 1), service.BLOCKER_POINTS)

        # **Drei Fehltermine wiegen die volle Leistungsspanne auf.** Daran ist die Höhe
        # kalibriert: die Perf-Achse ist breiter als der ganze beobachtete Topf, und bei
        # 2 Punkten verpuffte das Fehlen darin - an Saison 64 stand eine Lady mit drei
        # unentschuldigten Fehlterminen auf derselben Punktzahl wie zwei, die nie
        # gefehlt hatten.
        span = service.PERF_POINTS_MAX - service.PERF_POINTS_MIN
        self.assertEqual(3 * service.UNEXCUSED_POINTS, span)

    def test_every_perf_value_is_handed_out_exactly_once(self) -> None:
        """Zehn Plätze, zehn Punktwerte. Die Skala ist der **Topf**, nicht der Kader:
        "du bist die Schwächste von den zehn" ist eine Aussage, die im Gespräch trägt,
        "du liegst im 38. Perzentil des Kaders" ist keine."""
        # Jede fährt anders - bei echtem Gleichstand fiele ein Wert aus, und das ist
        # eine andere Regel (siehe test_an_identical_field_gets_identical_points).
        with sqlite3.connect(self.db_path) as conn:
            for offset in range(self.ROSTER):
                conn.execute(
                    "UPDATE matchscore SET score = ? WHERE player_id = ?",
                    (self.BASE_SCORE + offset * 1000, 100 + offset),
                )
        result = broom_service.rank()
        self.assertEqual(len(result.candidates), broom_service.SHORTLIST_SIZE)
        values = sorted(self._factor(c, "performance") for c in result.candidates)
        self.assertEqual(
            values,
            list(range(broom_service.PERF_POINTS_MIN, broom_service.PERF_POINTS_MAX + 1)),
        )
        # Die Schwächste oben, die Beste unten - und beide an den Enden der Skala.
        by_delta = sorted(result.candidates, key=lambda c: c.raw_delta)
        self.assertEqual(
            self._factor(by_delta[0], "performance"), broom_service.PERF_POINTS_MAX
        )
        self.assertEqual(
            self._factor(by_delta[-1], "performance"), broom_service.PERF_POINTS_MIN
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
        self.assertGreater(weak.besen, rest.besen)

    def test_fewer_kilometres_rank_worse(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE distance SET km = 20 WHERE player_id = 101")
            conn.execute("UPDATE distance SET km = 900 WHERE player_id = 102")
        result = broom_service.rank()
        order = [c.player_id for c in result.candidates]
        self.assertLess(order.index(101), order.index(102))

    def test_tenure_can_only_lower_the_score(self) -> None:
        """Zwei gleiche Kilometerwerte, verschieden lange dabei - der Schutz entscheidet."""
        self._give_history([101], 400)
        result = broom_service.rank()
        veteran = self._candidate(result, 101)
        rookie = self._candidate(result, 102)
        self.assertEqual(veteran.loyalty_points, broom_service.TREUE_MAX)
        self.assertLess(veteran.loyalty_points, rookie.loyalty_points)
        self.assertLess(veteran.besen, rookie.besen)

    def test_a_single_kilometre_week_is_enough_to_rank(self) -> None:
        """In einer laufenden Saison ist eine Woche oft die einzige - die beste
        vorhandene Zahl schlägt gar keine, und der Kopf nennt die Wochenzahl dazu."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance WHERE week > ?", (self.KM_WEEKS[0],))
            conn.execute("UPDATE distance SET km = 20 WHERE player_id = 101")
        result = broom_service.rank()
        self.assertEqual(result.km_weeks, 1)
        self.assertIsNotNone(self._factor(self._candidate(result, 101), "motivation"))

    def test_without_kilometres_everybody_pays_the_same_maximum(self) -> None:
        """Fehlen die Kilometer für alle, ist die Achse eine Konstante und die anderen
        drei reihen weiter. Die Ausgabe sagt trotzdem, dass die Zahlen fehlen - sonst
        liest sich eine ungelesene Truhe wie ein Kader, der nicht fährt."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance")
            conn.execute(
                "UPDATE matchscore SET score = ? WHERE player_id = 101",
                (self.BASE_SCORE - 9000,),
            )
        result = broom_service.rank()
        self.assertEqual(result.km_weeks, 0)
        self.assertEqual(result.candidates[0].player_id, 101)
        km_points = {self._factor(c, "motivation") for c in result.candidates}
        self.assertEqual(km_points, {broom_service.KM_POINTS_MAX})
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

    def test_the_roster_size_is_reported_without_a_target(self) -> None:
        """Die Zielzahl (`slots_to_free`, `TEAM_CAPACITY`, `TARGET_FREE_SLOTS`) ist
        weggefallen: sie stand in der Kopfzeile, die Kopfzeile ist weg, und eine Zahl,
        die nirgends mehr auftaucht, ist nur noch Pflege. Wie viele gehen sollen,
        entscheidet die Leitung, nicht die Liste."""
        result = broom_service.rank()
        self.assertEqual(result.roster_size, self.ROSTER)
        self.assertFalse(hasattr(result, "slots_to_free"))
        self.assertFalse(hasattr(broom_service, "TEAM_CAPACITY"))
        self.assertFalse(hasattr(broom_service, "TARGET_FREE_SLOTS"))

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
        """Die Fenstergröße muss die echte sein und nicht die angefragte: jede
        fenstergebundene Regel (die Kohortenschwelle voran) misst gegen sie."""
        self._short_season(length=15, history=0)
        result = broom_service.rank()
        self.assertEqual(result.window, 15)
        self.assertEqual(result.matches, 15)

    def test_kilometres_come_from_a_fixed_window_at_the_end_of_the_period(self) -> None:
        """Das Kilometerfenster ist **immer KM_WINDOW_WEEKS breit** und hängt am Ende
        des Wertungszeitraums - eine feste Punktschwelle braucht eine feste Breite,
        sonst hieße dieselbe Stufe in einer kurzen Saison etwas anderes als in einer
        langen. Eine Woche weit davor bleibt trotzdem draußen."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance WHERE player_id = 101")
            # Ein starker Wert, aber weit vor dem Fenster.
            conn.execute(
                "INSERT INTO distance (player_id, year, week, km) VALUES (101, 2025, 50, 900)"
            )
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
        self.assertEqual(candidate.km_weeks, 0)
        self.assertEqual(
            self._factor(candidate, "motivation"), broom_service.KM_POINTS_MAX
        )
        # Und der Teamschnitt darf die fremde Woche ebenso wenig sehen.
        self.assertAlmostEqual(result.team_km_average, 200.0)

    def test_the_kilometre_window_ends_with_the_period_not_today(self) -> None:
        """Sonst zöge eine abgeschlossene Saison die Kilometer von heute herein und
        wäre morgen nicht mehr reproduzierbar."""
        weeks = broom_service.last_weeks("2026-02-28", broom_service.KM_WINDOW_WEEKS)
        self.assertEqual(len(weeks), broom_service.KM_WINDOW_WEEKS)
        self.assertEqual(weeks[0], (2026, 9))
        self.assertEqual(weeks[-1], (2026, 5))
        self.assertEqual(len(set(weeks)), len(weeks))

    def test_only_the_weeks_inside_the_window_are_averaged(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO distance (player_id, year, week, km) VALUES (101, 2026, 20, 800)"
            )
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertEqual(candidate.km_weeks, len(self.KM_WEEKS))
        self.assertAlmostEqual(candidate.km_average, 200.0)

    def test_the_week_count_is_what_was_read_not_how_wide_the_window_is(self) -> None:
        """Die Truhe wird nicht jede Woche gelesen - "Schnitt aus fünf Wochen" wäre
        sonst eine Behauptung über Daten, die niemand eingetragen hat. Die Kopfzeile,
        in der das früher stand, ist weg; die Einschränkung steht jetzt in der Legende,
        und zwar nur dann, wenn sie vom Fenster abweicht."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance WHERE week > ?", (self.KM_WEEKS[0],))
        result = broom_service.rank()
        self.assertEqual(result.km_weeks, 1)
        text = self._flat(self.capture_stdout(broom_output.print_result, result))
        self.assertIn(f"letzten {broom_service.KM_WINDOW_WEEKS} Wochen", text)
        self.assertIn("1 davon in der Truhe eingetragen", text)

    def test_a_window_without_any_kilometre_week_says_so(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance")
        text = self.capture_stdout(broom_output.print_result, broom_service.rank())
        self.assertIn("Keine Kilometer im Zeitraum", text)

    def test_a_season_without_matches_is_reported_not_crashed(self) -> None:
        result = broom_service.rank(season=99)
        self.assertEqual(result.status, "NO_MATCHES")
        text = self.capture_stdout(broom_output.print_result, result)
        self.assertIn("Saison 99", text)

    def test_an_unknown_argument_is_refused_instead_of_ignored(self) -> None:
        """Sonst verschwindet jedes unbekannte Argument stillschweigend: ein getipptes
        ``--seson 64`` liefert kommentarlos die laufende Saison, und das abgeschaffte
        ``all`` aus Discord täte so, als hätte es gewirkt."""
        from modules import stats as stats_module

        for args in (["--all"], ["all"], ["--seson", "64"], ["--top", "3", "x"]):
            text = self.capture_stdout(lambda: stats_module._handle_broom(args))
            self.assertIn("Unbekannt", text, args)
            self.assertIn("Usage", text, args)
        # Und die gültigen gehen weiter durch.
        for args in ([], ["--top", "3"], ["--include-leaders"], ["--season", "2"]):
            self.assertEqual(stats_module._unknown_broom_args(args), [], args)

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

    def test_without_kilometre_weeks_the_axis_costs_the_maximum(self) -> None:
        """Keine Zahl ist kein Freifahrtschein. Früher fiel die Achse als "unbewertet"
        heraus und ihr Gewicht wurde umgelegt - in einem Punktesystem gibt es nichts
        umzulegen, also zahlt sie den Höchstsatz. Wer die Truhe nicht lesen lässt,
        steht wie jemand, der nicht fährt."""
        self._write("DELETE FROM distance WHERE player_id = 101", ())
        candidate = self._candidate(broom_service.rank(), 101)
        self.assertEqual(self._factor(candidate, "motivation"), broom_service.KM_POINTS_MAX)
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
        self.assertEqual(small.besen, large.besen)
        self.assertFalse(hasattr(result, "gp_slope"))

    def test_excused_absence_changes_no_score_but_is_still_reported(self) -> None:
        """Excused absence correlates with nothing (r = -0.03 against kilometres), so
        it is real life, not a signal - context in the reasons, never a factor."""
        before = self._candidate(broom_service.rank(), 101).besen
        for index in range(6):
            self._no_show(101, index, absent=1)
        candidate = self._candidate(broom_service.rank(), 101)

        self.assertEqual(candidate.excused, 6)
        self.assertEqual(candidate.unexcused, 0)
        self.assertNotIn("away", [factor.key for factor in candidate.factors])
        # Not through the contribution factor either: an excused row is out of the
        # denominator, so signing off costs her nothing at all.
        self.assertAlmostEqual(candidate.besen, before)
        self.assertTrue(any("zählt nicht" in reason for reason in candidate.reasons))

    def test_every_axis_carries_a_label_and_an_explanation(self) -> None:
        """Ohne beides ist eine Spalte in der Tabelle nicht erklärbar - und die Legende
        am Ende baut sich aus genau diesen Feldern auf."""
        for key, label, explanation in broom_service.FACTORS:
            self.assertTrue(key and label and explanation, key)
            self.assertIn(key, broom_service.FACTOR_PHRASES)
        # Gewichte gibt es nicht mehr: jede Achse trägt ihre Punkte direkt.
        self.assertFalse(hasattr(broom_service, "FACTOR_WEIGHTS"))

    def test_one_unexcused_absence_is_an_unconditional_ticket(self) -> None:
        """Vorgabe der Teamleitung: nicht zu erscheinen ist der eine Fehler, über den
        nicht verhandelt wird - auch nicht bei einer überdurchschnittlichen Fahrerin."""
        with sqlite3.connect(self.db_path) as conn:
            # P01 fährt deutlich über dem Feld und fehlt genau einmal.
            conn.execute(
                "UPDATE matchscore SET score = ? WHERE player_id = 101",
                (self.BASE_SCORE + 9000,),
            )
        self._give_history([101], 40)
        self._no_show(101, 3)
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
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
        self._give_history([101], 20)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE matchscore SET score = 0, points = 0 "
                "WHERE player_id = 101 AND match_id BETWEEN 200 AND 299"
            )
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
        self.assertIsNone(candidate.raw_delta)
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
        # Die Zahl steht in der Perf-Achse, wo auch die Punkte dafür herkommen - eine
        # zweite Zeile darunter hätte nur dasselbe noch einmal gesagt.
        perf = next(f for f in candidate.factors if f.key == "performance")
        self.assertIn("zum Match-Median", perf.detail)

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
        self.assertEqual(
            self._candidate(without, 101).besen, self._candidate(with_leaders, 101).besen
        )


class BroomOutputTests(BroomTestCase):
    def test_the_table_shows_the_real_values_with_points_beside_them(self) -> None:
        """**Der echte Wert führt, die Punkte stehen in Klammern daneben.** Mit "124
        km/Woche" kann eine Leaderin in ein Gespräch gehen, mit einer 2 nicht - und die
        Klammer sorgt dafür, dass sich die Gesamtzahl trotzdem nachaddieren lässt."""
        self._no_show(101, 3)
        result = broom_service.rank()
        candidate = self._candidate(result, 101)
        cells = broom_output._row(candidate, 1)
        for index, key in enumerate(broom_output.ORDER):
            factor = next(f for f in candidate.factors if f.key == key)
            cell = cells[3 + index].strip()
            if cell == "-":                     # nichts vorgefallen, nichts zu zeigen
                self.assertEqual(factor.points, 0)
                continue
            self.assertTrue(cell.startswith(factor.value), (cell, factor.value))
            self.assertTrue(cell.endswith(f"({factor.points})"), cell)
        self.assertEqual(int(cells[2]), candidate.besen)

    def test_the_table_stays_aligned(self) -> None:
        """Kopf, Trennlinie und jede Datenzeile sind gleich breit - eine Tabelle, die
        nur manchmal ausgerichtet ist, ist schlechter als eine ohne Spalten."""
        self._no_show(101, 3)
        self._no_show(102, 4, checkin=1)        # längste Fehlt-Zelle: "1+1 (5)"
        result = broom_service.rank()
        text = self.capture_stdout(broom_output.print_result, result)
        lines = text.splitlines()
        divider = next(line for line in lines if line.startswith("---"))
        header = next(line for line in lines if "Lady" in line)
        rows = [line for line in lines if line[:2].strip().isdigit()]
        self.assertTrue(rows)
        self.assertEqual(len(divider), broom_output.WIDTH)
        for line in [header, *rows]:
            self.assertEqual(len(line), len(divider), line)

    def test_the_reasons_survive_in_json_but_are_not_printed(self) -> None:
        """Die Begründungsblöcke pro Person sind aus der Ausgabe raus - die Tabelle
        trägt die echten Werte, das Punktesystem darunter erklärt sie, und damit steht
        jede Zeile für sich. Was die Blöcke zusätzlich wussten (Quote gegen den
        Teamschnitt, Einbrüche, Vorfälle vor dem Fenster), bleibt in ``--json``."""
        for index in (3, 4, 5):
            self._no_show(101, index)
        result = broom_service.rank()
        self.assertTrue(all(candidate.reasons for candidate in result.candidates[:5]))
        text = self.capture_stdout(broom_output.print_result, result)
        self.assertNotIn("unentschuldigt in", text)
        self.assertNotIn("Besenpunkte\n   ", text)
        payload = json.loads(self.capture_stdout(broom_output.print_json, result))
        self.assertTrue(payload["candidates"][0]["reasons"])

    def test_the_output_fits_into_one_discord_message(self) -> None:
        """**Eine** Nachricht, und das ist seit dem Wegfall der Begründungsblöcke die
        Latte. Vorher waren es zwei (und ``--all`` brauchte drei), weil jede Kandidatin
        vier Achsenzeilen plus Kontext bekam. Jetzt trägt die Tabelle alles, was im
        Gespräch gebraucht wird, und das Punktesystem darunter erklärt sie einmal für
        alle. Das hier ist die Zahl, die nicht unbemerkt wieder wachsen darf.
        """
        max_discord_msg_len = 1990
        result = broom_service.rank()
        text = self.capture_stdout(lambda: broom_output.print_result(result))
        self.assertLess(len(text), max_discord_msg_len)

    def test_top_shortens_the_table_itself(self) -> None:
        """``--top`` kürzte früher die Begründungsblöcke. Die gibt es nicht mehr, also
        kürzt es jetzt die Tabelle - das ist auch die Lesart, die `.B 5` im Bot nahelegt."""
        result = broom_service.rank()
        full = self.capture_stdout(lambda: broom_output.print_result(result))
        short = self.capture_stdout(lambda: broom_output.print_result(result, limit=3))
        rows = lambda text: [l for l in text.splitlines() if l[:2].strip().isdigit()]
        self.assertEqual(len(rows(full)), len(result.candidates))
        self.assertEqual(len(rows(short)), 3)
        # Das Punktesystem bleibt, auch gekürzt - ohne es ist die Tabelle nicht lesbar.
        self.assertIn("Besenpunkte", short)

    def test_the_wording_judges_the_driving_and_not_the_person(self) -> None:
        """Vorgabe der Teamleitung. Die Liste geht in ein Gespräch, in dem jemand
        erfährt, dass sie gehen soll - "die Schwächste" kommt dort nicht an, und es ist
        auch nicht gemeint: bewertet wird eine Fahrleistung in einem Zeitraum, kein
        Mensch. Deshalb steht in der Legende "die geringste Fahrleistung"."""
        self._no_show(101, 3)
        text = self._flat(
            self.capture_stdout(lambda: broom_output.print_result(broom_service.rank()))
        )
        for word in ("schwäch", "schlecht", "versag", "faul", "mies"):
            self.assertNotIn(word, text.lower(), word)
        self.assertIn("geringste Fahrleistung", text)
        # Der Gleichstand wird von unten erklärt, nicht von oben.
        self.assertIn("wer mehr eingefahren hat", text)

    def test_nothing_is_wider_than_the_table(self) -> None:
        """Sonst läuft die Erklärung im Discord-Codeblock seitlich weg, während die
        Tabelle daneben ordentlich endet. Der Umbruch wird gerechnet und nicht von Hand
        gesetzt - sonst reicht ein Wort mehr in einer Schwelle, und es steht wieder über.
        """
        import unicodedata

        def display_width(line: str) -> int:
            return sum(
                2 if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) > 0x1F000
                else 1
                for ch in line
            )

        # Ein Kader mit vielen Fehlterminen macht die Topf-Zeile lang, ein Fenster
        # ohne Truhe fügt die Warnzeile hinzu, --include-leaders den Kopfzusatz.
        for index in range(3, 9):
            self._no_show(101 + index, index)
        cases = [
            ({}, broom_service.rank()),
            ({"limit": 3}, broom_service.rank()),
            ({}, broom_service.rank(include_leaders=True)),
        ]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance")
        cases.append(({}, broom_service.rank()))
        for args, result in cases:
            text = self.capture_stdout(
                lambda: broom_output.print_result(result, **args)
            )
            for line in text.splitlines():
                self.assertLessEqual(display_width(line), broom_output.WIDTH, line)

    def test_the_legend_spells_out_the_whole_point_system(self) -> None:
        """Der Kern des Umbaus: nicht "vertrau der Liste", sondern "rechne nach". Dafür
        muss **jede Schwelle** in der Legende stehen, nicht nur, was die Spalte
        bedeutet - sonst fehlt genau die Zahl, die jemand braucht."""
        svc = broom_service
        text = self._flat(self.capture_stdout(lambda: broom_output.print_result(svc.rank())))
        for _, label, _ in svc.FACTORS:
            self.assertIn(label, text)
        # **Jede Staffelgrenze mit ihrem Vergleichszeichen.** Die beiden Staffeln
        # meinen es verschieden - Kilometer greifen bei <=, Matches bei < -, und eine
        # Legende, die das verwischt, ist genau an der Grenze falsch, an der jemand
        # nachschaut.
        for limit, points in svc.KM_TIERS:
            self.assertIn(f"<={limit} {points:+d}", text)
        for limit, points in svc.TREUE_TIERS:
            self.assertIn(f"<{limit} {points:+d}", text)
        self.assertIn(f"ab {svc.TREUE_TIERS[-1][0]} {svc.TREUE_MAX:+d}", text)
        self.assertIn(f"darüber {svc.KM_POINTS_MIN:+d}", text)
        self.assertIn(f"+{svc.UNEXCUSED_POINTS} je Mal", text)
        self.assertIn(f"+{svc.BLOCKER_POINTS} je Mal", text)
        self.assertIn(f"+{svc.PERF_POINTS_MAX}", text)
        self.assertIn(f"+{svc.PERF_POINTS_MIN}", text)
        self.assertIn(f"letzten {svc.KM_WINDOW_WEEKS} Wochen", text)
        self.assertIn("Gleichstand", text)
        self.assertIn("Entschuldigtes Fehlen zählt nirgends", text)

    def test_the_tiebreaker_stands_in_the_table(self) -> None:
        """Er reiht nicht mit, aber bei Gleichstand entscheidet er den Platz - und dann
        muss man ihn sehen können, ohne die Liste zu verlassen."""
        self._no_show(101, 3)
        result = broom_service.rank()
        candidate = result.candidates[0]
        self.assertEqual(
            int(broom_output._row(candidate, 1)[-1]), candidate.points_total
        )
        text = self.capture_stdout(lambda: broom_output.print_result(result))
        header = next(l for l in text.splitlines() if "Lady" in l)
        self.assertTrue(header.rstrip().endswith(broom_service.TIEBREAK_LABEL), header)
        # Und die Legende sagt, in welche Richtung er wirkt.
        self.assertIn("Bei Gleichstand", text)
        self.assertIn("weiter unten", text)

    def test_the_points_in_the_table_add_up_to_the_total(self) -> None:
        """Die Klammern müssen sich zur Gesamtzahl nachaddieren lassen - das ist der
        Vertrag, auf dem der ganze Umbau steht. Wer die vier Klammern zusammenzählt
        und etwas anderes herausbekommt als die Besen-Spalte, kann nicht nachrechnen."""
        self._no_show(101, 3)
        result = broom_service.rank()
        for candidate in result.candidates:
            cells = broom_output._row(candidate, 1)
            total = 0
            for index in range(len(broom_output.ORDER)):
                cell = cells[3 + index].strip()
                total += 0 if cell == "-" else int(cell.rsplit("(", 1)[1].rstrip(")"))
            self.assertEqual(total, candidate.besen, cells)
            self.assertEqual(int(cells[2]), candidate.besen)

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
        labels = [label for _, label, _ in broom_service.FACTORS]
        labels += [broom_service.BESEN_LABEL, broom_service.TIEBREAK_LABEL]
        for label in labels:
            self.assertTrue(label.isascii(), label)
            self.assertTrue(label.replace("/", "").isalnum(), label)
        text = self.capture_stdout(broom_output.print_result, broom_service.rank())
        header = next(line for line in text.splitlines() if "Lady" in line)
        self.assertTrue(header.isascii(), header)

    def test_json_carries_the_factors_for_a_downstream_reader(self) -> None:
        import json

        payload = json.loads(self.capture_stdout(broom_output.print_json, broom_service.rank()))
        self.assertEqual(payload["status"], "OK")
        self.assertEqual(len(payload["candidates"][0]["factors"]), len(broom_service.FACTORS))

    def test_an_identical_field_gets_identical_points(self) -> None:
        """Alle fahren gleich: dann sagt die Perf-Achse nichts, und sie muss für alle
        dasselbe sagen. Ein laufender Index hätte hier je nach Sortierstabilität
        verschiedene Punkte vergeben - deshalb zählt sie, wie viele *echt* schwächer
        sind, und das ist bei Gleichstand für alle null."""
        self.assertFalse(hasattr(broom_service, "_percentile"))
        result = broom_service.rank()
        perf = {self._factor(c, "motivation") for c in result.candidates}
        self.assertEqual(len(perf), 1)
        self.assertEqual(
            len({self._factor(c, "performance") for c in result.candidates}), 1
        )
        self.assertEqual(len({c.besen for c in result.candidates}), 1)

    def test_every_candidate_names_the_kilometres_that_ranked_her(self) -> None:
        """Ein Name mit leerem Block darunter liest sich als Fehler - und eine
        Begründung, die das Reihungskriterium verschweigt, taugt für kein Gespräch.
        Deshalb stehen die Kilometer immer da, nicht erst unter einer Schwelle."""
        for candidate in broom_service.rank().candidates:
            km = next(f for f in candidate.factors if f.key == "motivation")
            self.assertIn("km/Woche", km.detail)
            self.assertTrue(all(f.detail for f in candidate.factors), candidate.name)

    def test_without_kilometre_data_the_block_says_so(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM distance")
        for candidate in broom_service.rank().candidates:
            km = next(f for f in candidate.factors if f.key == "motivation")
            self.assertEqual(km.detail, "keine Kilometer im Zeitraum gemeldet")
            self.assertEqual(km.points, broom_service.KM_POINTS_MAX)

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
        # Ohne Kohorte gibt es keinen Maßstab für die Perf-Achse, also zahlt sie für
        # alle den Höchstsatz - das ist ehrlicher als ein Perzentil aus dem Nichts,
        # und die drei anderen Achsen reihen weiter.
        text = self.capture_stdout(lambda: broom_output.print_result(result))
        self.assertIn("Besenpunkte", text)
        for candidate in result.candidates:
            self.assertEqual(
                self._factor(candidate, "performance"), broom_service.PERF_POINTS_MAX
            )

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
