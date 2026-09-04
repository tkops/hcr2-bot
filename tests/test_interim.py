from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest import mock

from hcr2.models.video import VideoEntry, VideoResults
from hcr2.output import interim as interim_output
from hcr2.services import interim as interim_service
from hcr2.services import videos as video_service
from modules import video as video_module
from tests.support import TemporaryDatabaseTestCase


BASE = 50_000


class InterimReportTests(TemporaryDatabaseTestCase):
    """The running match: nobody is written, everybody is compared against her own
    earlier score from the same event."""

    def setUp(self) -> None:
        super().setUp()
        self.pids = list(range(10, 20))
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO players (id, name, alias, garage_power, active, team)
                VALUES (?, ?, ?, 5000, 1, 'PLTE')
                """,
                [(pid, f"Lady{pid}", f"lady{pid}") for pid in self.pids],
            )
            # The event's second match - same tracks, so match 1 is the yardstick.
            conn.execute(
                """
                INSERT INTO match (id, teamevent_id, season_number, start, opponent)
                VALUES (2, 1, 2, '2021-06-07', 'Rivals')
                """
            )
            conn.executemany(
                "INSERT INTO matchscore (match_id, player_id, score, points) VALUES (1, ?, ?, 10)",
                [(pid, BASE) for pid in self.pids],
            )
            # Alice drove nothing in this event, so she never lands in the ratio lists.
            conn.execute("UPDATE players SET active = 0 WHERE id = 1")

    def build(self, entries, **kwargs) -> VideoResults:
        defaults = dict(match_id=2, score_ladys=100, score_opponent=200,
                        opponent="Rivals", time_left="4h30m")
        defaults.update(kwargs)
        return VideoResults(entries=entries, **defaults)

    def report(self, entries, **kwargs):
        return interim_service.build_report(self.build(entries, **kwargs), match_id=2)

    def flat_run(self, *, factor: float = 1.0, skip: int = 0) -> list[VideoEntry]:
        """Everybody at the same share of her match-1 score - the normal case."""
        return [
            VideoEntry(pid=pid, score=int(BASE * factor), points=10)
            for pid in self.pids[skip:]
        ]

    def test_a_whole_team_driving_at_the_same_share_flags_nobody(self) -> None:
        report = self.report(self.flat_run(factor=0.5))

        self.assertEqual(report.status, "OK")
        self.assertEqual(report.driven, len(self.pids))
        self.assertEqual(report.aborted, [])
        self.assertEqual(report.behind, [])
        self.assertEqual(report.improved, [])

    def test_a_single_broken_off_run_is_flagged_against_the_team_pace(self) -> None:
        entries = self.flat_run(factor=1.0)
        entries[0] = VideoEntry(pid=self.pids[0], score=int(BASE * 0.4), points=1)

        report = self.report(entries)

        self.assertEqual([player.pid for player in report.aborted], [self.pids[0]])
        self.assertEqual(report.behind, [])

    def test_being_behind_the_team_pace_lands_in_the_push_list_not_in_aborted(self) -> None:
        entries = self.flat_run(factor=1.0)
        entries[0] = VideoEntry(pid=self.pids[0], score=int(BASE * 0.8), points=5)

        report = self.report(entries)

        self.assertEqual(report.aborted, [])
        self.assertEqual([player.pid for player in report.behind], [self.pids[0]])

    def test_the_team_improving_together_does_not_make_everyone_a_top_improver(self) -> None:
        """Within an event the later matches are systematically better - measured live at
        1.04x. Without the pace division the praise list would be the whole roster."""
        entries = self.flat_run(factor=1.3)
        entries[0] = VideoEntry(pid=self.pids[0], score=int(BASE * 1.8), points=20)

        report = self.report(entries)

        self.assertEqual([player.pid for player in report.improved], [self.pids[0]])

    def test_a_huge_gain_over_a_broken_base_is_not_praised(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            # Her match-1 score was itself far below what she usually drives.
            conn.execute("UPDATE matchscore SET score = 5000 WHERE match_id = 1 AND player_id = 10")
            # Her own level, from enough earlier matches to be more than an anecdote -
            # in another event, so they do not become the reference for this one.
            conn.execute(
                """
                INSERT INTO teamevent (id, name, iso_year, iso_week, tracks, max_score_per_track)
                VALUES (2, 'Older Cup', 2021, 18, 4, 15000)
                """
            )
            conn.executemany(
                """
                INSERT INTO match (id, teamevent_id, season_number, start, opponent)
                VALUES (?, 2, 2, ?, 'Older')
                """,
                [(3, "2021-05-01"), (4, "2021-05-03"), (5, "2021-05-05")],
            )
            conn.executemany(
                "INSERT INTO matchscore (match_id, player_id, score, points) VALUES (?, 10, ?, 10)",
                [(3, BASE), (4, BASE), (5, BASE)],
            )

        report = self.report(self.flat_run(factor=1.0))

        # +900 % over a base of 5000 that was itself an outlier says "back to normal".
        self.assertEqual([player.pid for player in report.improved], [])

    def wide_roster(self, *, low: int, factor: float):
        """A roster big enough that the low group stays a minority - otherwise it *is* the
        team's pace and by definition nobody is behind it."""
        extra = list(range(20, 30))
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO players (id, name, alias, garage_power, active, team)
                VALUES (?, ?, ?, 5000, 1, 'PLTE')
                """,
                [(pid, f"Lady{pid}", f"lady{pid}") for pid in extra],
            )
            conn.executemany(
                "INSERT INTO matchscore (match_id, player_id, score, points) VALUES (1, ?, ?, 10)",
                [(pid, BASE) for pid in extra],
            )
        pids = self.pids + extra
        entries = [VideoEntry(pid=pid, score=BASE, points=10) for pid in pids]
        for index in range(low):
            entries[index] = VideoEntry(pid=pids[index], score=int(BASE * factor), points=5)
        return entries

    def section(self, text: str, heading: str) -> list[str]:
        block = text.split(heading, 1)[1].split("\n\n", 1)[0]
        return [line for line in block.splitlines() if line]

    def test_behind_holds_five_names_and_never_names_a_rest(self) -> None:
        """Vorgabe der Teamleitung: "Luft nach oben" ist die Liste, auf die sie zugeht, also
        fuenf Namen - und ohne Restzaehler, der nur Platz kostet."""
        report = self.report(self.wide_roster(low=7, factor=0.8))
        text = interim_output.format_report(report)

        self.assertEqual(len(report.behind), interim_service.BEHIND_LIMIT)
        self.assertEqual(len(self.section(text, "Luft nach oben**")), 5)
        self.assertNotIn("weitere", text)
        self.assertFalse(hasattr(report, "behind_more"))

    def test_aborted_still_holds_three_names_and_counts_the_rest(self) -> None:
        report = self.report(self.wide_roster(low=4, factor=0.4))
        text = interim_output.format_report(report)

        self.assertEqual(len(report.aborted), interim_service.TOP_LIMIT)
        self.assertEqual(report.aborted_more, 1)
        self.assertIn("und 1 weitere", text)

    def test_newcomers_are_listed_whether_they_drove_or_not(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO players (id, name, alias, garage_power, active, team)
                VALUES (?, ?, ?, 1000, 1, 'PLTE')
                """,
                [(80, "Neu Gefahren", "neu1"), (81, "Neu Wartet", "neu2")],
            )
            # Lady10 hat drei gefahrene Matches hinter sich, ist also keine Neue mehr.
            conn.executemany(
                """
                INSERT INTO match (id, teamevent_id, season_number, start, opponent)
                VALUES (?, 1, 2, ?, 'Older')
                """,
                [(3, "2021-05-01"), (4, "2021-05-03")],
            )
            conn.executemany(
                "INSERT INTO matchscore (match_id, player_id, score, points) VALUES (?, 10, 50000, 10)",
                [(3,), (4,)],
            )

        entries = self.flat_run(factor=1.0)
        entries.append(VideoEntry(pid=80, score=42_000, points=3))

        report = self.report(entries)
        listed = {player.pid: (player.score, player.note) for player in report.newcomers}

        self.assertEqual(listed[80], (42_000, "1. Match"))
        self.assertEqual(listed[81], (0, "1. Match"))
        # Everybody with three matches behind her stays out of the watch list.
        self.assertNotIn(self.pids[0], listed)

    def test_players_without_a_score_are_split_by_reason(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE players SET away_from = '2021-06-01', away_until = '2021-06-30' WHERE id = 11"
            )

        entries = self.flat_run(factor=1.0, skip=3)
        entries.append(VideoEntry(pid=self.pids[2], score=0, points=0, checkin=1))

        report = self.report(entries)
        states = {player.pid: player.state for player in report.not_driven}

        self.assertEqual(states[self.pids[0]], "open")
        self.assertEqual(states[self.pids[1]], "away")
        self.assertEqual(states[self.pids[2]], "checkin")

    def test_the_first_match_of_an_event_falls_back_to_the_cross_event_average(self) -> None:
        report = interim_service.build_report(
            self.build([VideoEntry(pid=pid, score=BASE, points=10) for pid in self.pids], match_id=1),
            match_id=1,
        )

        self.assertEqual(report.reference, "history")
        self.assertEqual(report.position, 1)

    def test_a_row_that_could_not_be_assigned_is_reported_not_dropped(self) -> None:
        entries = self.flat_run(factor=1.0)
        entries.append(VideoEntry(pid=0, score=42_000, points=7, name="Elias18"))

        report = self.report(entries)

        self.assertTrue(any("Elias18" in warning for warning in report.warnings))

    def test_a_reading_without_a_countdown_is_questioned(self) -> None:
        report = self.report(self.flat_run(), time_left="")

        self.assertTrue(any("time_left" in warning for warning in report.warnings))

    def test_the_wrong_opponent_is_an_error(self) -> None:
        report = self.report(self.flat_run(), opponent="Totally Different Team")

        self.assertTrue(report.errors)

    def test_nothing_is_written(self) -> None:
        self.report(self.flat_run(factor=0.4))

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT COUNT(*) FROM matchscore WHERE match_id = 2").fetchone()[0]
            totals = conn.execute("SELECT score_ladys, score_opponent FROM match WHERE id = 2").fetchone()
        self.assertEqual(rows, 0)
        self.assertEqual(tuple(totals), (0, 0))


class InterimCleanupCommandTests(TemporaryDatabaseTestCase):
    """Aufräumen und Berichten sind zwei Schritte. Das Aufräumen wird typisch später
    nachgeholt, wenn die Lesung nicht mehr im Standardpfad liegt - hing es am Lesen,
    brach `--cleanup` mit "results file not found" ab, ohne die Datei anzufassen."""

    def setUp(self) -> None:
        super().setUp()
        self.calls: list[str | None] = []
        patch = mock.patch.object(
            video_service, "cleanup_interim_video",
            side_effect=lambda match_id, **kw: (self.calls.append(kw.get("filename")), ("DELETED", "1-tmp.mp4"))[1],
        )
        patch.start()
        self.addCleanup(patch.stop)
        # Der Standardpfad der Lesung liegt im Temp-Verzeichnis, nicht im Repo.
        self.default = Path(self.tempdir.name) / "results.json"
        path_patch = mock.patch.object(video_service, "results_path", return_value=self.default)
        path_patch.start()
        self.addCleanup(path_patch.stop)

    def run_cli(self, *args) -> str:
        return self.capture_stdout(video_module.handle_command, "interim", list(args))

    def test_cleanup_runs_without_any_reading(self) -> None:
        output = self.run_cli("--match", "1", "--cleanup", "--video", "1-tmp.mp4")

        self.assertEqual(self.calls, ["1-tmp.mp4"])
        # Kein ❌: main() macht daran den Exit-Code fest, ein geglücktes Aufräumen
        # dürfte sonst als Fehlschlag enden.
        self.assertNotIn("❌", output)
        self.assertNotIn("results file not found", output)

    def test_a_broken_reading_is_still_reported_and_does_not_stop_the_cleanup(self) -> None:
        self.default.write_text("{not json", encoding="utf-8")

        output = self.run_cli("--match", "1", "--cleanup")

        self.assertIn("❌", output)
        self.assertEqual(len(self.calls), 1)

    def test_a_missing_file_named_explicitly_is_still_an_error(self) -> None:
        """Wer `--file` angibt, meint diese Datei - deren Fehlen ist ein echter Befund."""
        output = self.run_cli("--match", "1", "--cleanup", "--file", "nope.json")

        self.assertIn("❌", output)
        self.assertEqual(len(self.calls), 1)

    def test_without_cleanup_a_missing_reading_stays_an_error(self) -> None:
        output = self.run_cli("--match", "1")

        self.assertIn("❌", output)
        self.assertEqual(self.calls, [])


class InterimGuardTests(TemporaryDatabaseTestCase):
    """An interim reading must not become a result: the 0/0 rows would read as
    unexcused no-shows in every average afterwards."""

    def test_apply_refuses_a_reading_that_carries_a_countdown(self) -> None:
        results = VideoResults(
            match_id=1, score_ladys=200, score_opponent=111, opponent="Rivals",
            time_left="16h07m",
            entries=[VideoEntry(pid=1, score=50_000, points=200)],
        )

        outcome = video_service.apply_results(results, match_id=1, dry_run=True)

        self.assertEqual(outcome.status, "VALIDATION_ERRORS")
        self.assertTrue(any("time_left" in error for error in outcome.errors))

    def test_force_downgrades_the_countdown_to_a_warning(self) -> None:
        results = VideoResults(
            match_id=1, score_ladys=200, score_opponent=111, opponent="Rivals",
            time_left="16h07m",
            entries=[VideoEntry(pid=1, score=50_000, points=200)],
        )

        outcome = video_service.apply_results(results, match_id=1, dry_run=True, force=True)

        self.assertEqual(outcome.status, "DRY_RUN")
        self.assertTrue(any("time_left" in warning for warning in outcome.warnings))

    def test_the_countdown_survives_the_results_file(self) -> None:
        path = Path(self.tempdir.name) / "interim.json"
        path.write_text(json.dumps({
            "match_id": 1, "score_ladys": 5, "score_opponent": 6, "time_left": " 16h07m ",
            "entries": [{"pid": 1, "score": 1000, "points": 5}],
        }), encoding="utf-8")

        results, errors = video_service.load_results(path)

        self.assertEqual(errors, [])
        self.assertEqual(results.time_left, "16h07m")


class InterimOutputTests(TemporaryDatabaseTestCase):
    def test_the_report_names_every_block_it_has_content_for(self) -> None:
        report = interim_service.build_report(
            VideoResults(
                match_id=1, score_ladys=200, score_opponent=111, opponent="Rivals",
                time_left="16h07m",
                entries=[VideoEntry(pid=1, score=0, points=0, checkin=1)],
            ),
            match_id=1,
        )
        text = interim_output.format_report(report)

        self.assertIn("Zwischenstand Match 1", text)
        self.assertIn("noch 16h07m", text)
        self.assertIn("Noch nicht gefahren", text)
        self.assertIn("Nichts eingetragen", text)

    def test_the_report_stays_inside_one_discord_message(self) -> None:
        """It is meant to be posted as it is - a split report puts the ranking in one
        message and the reasons in another."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO players (id, name, alias, garage_power, active, team)
                VALUES (?, ?, ?, 5000, 1, 'PLTE')
                """,
                [(pid, f"Langer Name {pid}", f"lady{pid}") for pid in range(20, 70)],
            )
            conn.execute(
                """
                INSERT INTO match (id, teamevent_id, season_number, start, opponent)
                VALUES (2, 1, 2, '2021-06-07', 'Rivals')
                """
            )
            conn.executemany(
                """
                INSERT INTO match (id, teamevent_id, season_number, start, opponent)
                VALUES (?, 1, 2, ?, 'Older')
                """,
                [(3, "2021-05-01"), (4, "2021-05-03")],
            )
            # Drei gefahrene Matches pro Spielerin: keine Neuzugänge, damit der Test die
            # lange Namensliste misst und nicht den Neu-im-Team-Block.
            conn.executemany(
                "INSERT INTO matchscore (match_id, player_id, score, points) VALUES (?, ?, 50000, 10)",
                [(match_id, pid) for match_id in (1, 3, 4) for pid in range(20, 70)],
            )

        report = interim_service.build_report(
            VideoResults(
                match_id=2, score_ladys=200, score_opponent=111, opponent="Rivals",
                time_left="16h07m",
                entries=[VideoEntry(pid=pid, score=0, points=0) for pid in range(20, 70)],
            ),
            match_id=2,
        )
        text = interim_output.format_report(report)

        self.assertLess(len(text), 1990)
