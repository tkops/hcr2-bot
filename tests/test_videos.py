from __future__ import annotations

import json
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from hcr2.integrations import nextcloud
from hcr2.models.video import VideoCandidate, VideoEntry, VideoResults
from hcr2.output import videos as video_output
from hcr2.services import videos as video_service
from hcr2.services.videos import compare_opponent
from tests.support import TemporaryDatabaseTestCase


PROPFIND_XML = b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/user/Power-Ladys-Scores/Team-Event/S2/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/user/Power-Ladys-Scores/Team-Event/S2/1_Teamcup_Rivals.xlsx</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Mon, 10 Aug 2026 10:00:00 GMT</d:getlastmodified>
      <d:getcontentlength>4711</d:getcontentlength>
      <d:resourcetype/>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/user/Power-Ladys-Scores/Team-Event/S2/1%20Final%20Standings.mp4</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Tue, 11 Aug 2026 12:00:00 GMT</d:getlastmodified>
      <d:getcontentlength>1048576</d:getcontentlength>
      <d:resourcetype/>
    </d:prop></d:propstat>
  </d:response>
</d:multistatus>
"""


def candidate(name: str, *, days: int = 0, size: int = 10) -> VideoCandidate:
    return VideoCandidate(
        name=name,
        remote_path=f"Power-Ladys-Scores/Team-Event/S2/{name}",
        size=size,
        last_modified=datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(days=days),
    )


class PropfindParsingTests(unittest.TestCase):
    def test_list_directory_returns_files_without_the_collection_itself(self) -> None:
        response = mock.Mock(status_code=207, content=PROPFIND_XML)
        with mock.patch.object(nextcloud, "NEXTCLOUD_AUTH", ("user", "secret")), \
                mock.patch.object(nextcloud.requests, "request", return_value=response) as request:
            entries = nextcloud.list_directory("Power-Ladys-Scores/Team-Event/S2")

        self.assertEqual(request.call_args.args[0], "PROPFIND")
        self.assertEqual(request.call_args.kwargs["headers"]["Depth"], "1")
        self.assertEqual([entry.name for entry in entries], ["1_Teamcup_Rivals.xlsx", "1 Final Standings.mp4"])
        self.assertEqual(entries[0].size, 4711)
        self.assertEqual(entries[1].last_modified.year, 2026)
        self.assertFalse(any(entry.is_dir for entry in entries))

    def test_list_directory_reports_failures_as_an_empty_list(self) -> None:
        response = mock.Mock(status_code=404, content=b"")
        with mock.patch.object(nextcloud, "NEXTCLOUD_AUTH", ("user", "secret")), \
                mock.patch.object(nextcloud.requests, "request", return_value=response):
            self.assertEqual(nextcloud.list_directory("Power-Ladys-Scores/Team-Event/S2"), [])


class CandidateSelectionTests(unittest.TestCase):
    def test_video_named_after_the_match_wins_over_the_newer_one(self) -> None:
        candidates = [candidate("799.mp4", days=1), candidate("IMG_4711.mov", days=5)]
        picked = video_service.select_candidate(799, candidates)
        self.assertEqual(picked.name, "799.mp4")

    def test_without_a_matching_name_the_newest_video_is_used(self) -> None:
        candidates = sorted(
            [candidate("old.mp4", days=1), candidate("new.mov", days=5)],
            key=video_service._sort_key,
            reverse=True,
        )
        picked = video_service.select_candidate(799, candidates)
        self.assertEqual(picked.name, "new.mov")

    def test_explicit_filename_is_matched_case_insensitively(self) -> None:
        candidates = [candidate("799.mp4"), candidate("Other.MP4")]
        self.assertEqual(video_service.select_candidate(799, candidates, filename="other.mp4").name, "Other.MP4")
        self.assertIsNone(video_service.select_candidate(799, candidates, filename="missing.mp4"))

    def test_match_id_prefixes(self) -> None:
        self.assertTrue(video_service.matches_match_id("799.mp4", 799))
        self.assertTrue(video_service.matches_match_id("799_Nitro_Canada.mp4", 799))
        self.assertFalse(video_service.matches_match_id("7990.mp4", 799))
        self.assertFalse(video_service.matches_match_id("1799.mp4", 799))

    def test_an_unrelated_filename_is_flagged_even_when_it_is_the_only_video(self) -> None:
        from hcr2.models.video import PullOutcome

        outcome = PullOutcome(
            status="OK",
            local_path=Path("tmp/video/799/IMG_4711.mov"),
            candidate=candidate("IMG_4711.mov"),
            candidates=[candidate("IMG_4711.mov")],
            season=2,
        )
        buffer: list[str] = []
        with mock.patch("builtins.print", side_effect=lambda *a, **k: buffer.append(" ".join(str(x) for x in a))):
            video_output.print_ambiguity_warning(outcome, match_id=799)
        self.assertTrue(any("does not name match 799" in line for line in buffer))


class FrameExtractionTests(unittest.TestCase):
    def test_ffmpeg_command_carries_fps_crop_and_scale(self) -> None:
        command = video_service.build_ffmpeg_command(
            Path("tmp/video/1/a.mp4"), Path("tmp/video/1/frames"), fps=2, width=1200, crop="1000:800:100:200"
        )
        self.assertIn("-vf", command)
        self.assertEqual(command[command.index("-vf") + 1], "fps=2,crop=1000:800:100:200,scale=1200:-2")
        self.assertTrue(command[-1].endswith(video_service.FRAME_PATTERN))

    def test_missing_ffmpeg_is_reported_before_anything_is_downloaded(self) -> None:
        downloader = mock.Mock()
        outcome = video_service.extract_frames(
            1, ffmpeg_resolver=lambda: None, downloader=downloader, lister=lambda _: []
        )
        self.assertEqual(outcome.status, "FFMPEG_MISSING")
        downloader.assert_not_called()

    def test_ffmpeg_is_looked_up_in_path_env_and_imageio(self) -> None:
        with mock.patch.dict("os.environ", {video_service.FFMPEG_ENV: "/nope/ffmpeg"}, clear=False):
            self.assertIsNone(video_service.resolve_ffmpeg())
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(video_service.shutil, "which", return_value="/usr/bin/ffmpeg"):
            self.assertEqual(video_service.resolve_ffmpeg(), "/usr/bin/ffmpeg")

    def test_ffmpeg_failure_keeps_the_stderr_reason(self) -> None:
        with mock.patch.object(video_service, "pull_video") as pull:
            pull.return_value = mock.Mock(status="OK", local_path=Path("tmp/video/1/a.mp4"))
            with mock.patch.object(Path, "mkdir"), mock.patch.object(Path, "glob", return_value=[]):
                outcome = video_service.extract_frames(
                    1,
                    ffmpeg_resolver=lambda: "/usr/bin/ffmpeg",
                    runner=lambda cmd: subprocess.CompletedProcess(cmd, 1, "", "Invalid data found"),
                )
        self.assertEqual(outcome.status, "FFMPEG_FAILED")
        self.assertEqual(outcome.detail, "Invalid data found")


class OpponentComparisonTests(unittest.TestCase):
    def test_case_spaces_accents_and_emoji_do_not_count(self) -> None:
        for read, stored in (
            ("TEAM CANADA", "Team Canada"),
            ("Join Us Poland", "JoinUs  Poland"),
            ("UKRAINE 🇺🇦", "Ukraine"),
            ("Ĺegacy", "Legacy"),
            ("Norway2", "Norway 2"),
        ):
            with self.subTest(read=read):
                self.assertEqual(compare_opponent(read, stored)[0], "MATCH")

    def test_a_truncated_video_name_still_counts_as_the_same_team(self) -> None:
        self.assertEqual(compare_opponent("Legacy", "Legacy Reborn")[0], "CLOSE")

    def test_a_short_stem_is_not_enough(self) -> None:
        self.assertEqual(compare_opponent("PL", "PLTE Ladys")[0], "MISMATCH")

    def test_a_different_team_is_a_mismatch(self) -> None:
        verdict, similarity = compare_opponent("2MuchClutch", "TEAM CANADA")
        self.assertEqual(verdict, "MISMATCH")
        self.assertLess(similarity, 0.5)

    def test_names_without_comparable_characters(self) -> None:
        self.assertEqual(compare_opponent("🔥🔥", "Legacy")[0], "UNCOMPARABLE")
        self.assertEqual(compare_opponent("", "Legacy")[0], "UNCOMPARABLE")


class ResultsFileTests(unittest.TestCase):
    def test_broken_json_is_reported_instead_of_raising(self) -> None:
        with mock.patch.object(Path, "read_text", return_value="{nope"):
            results, errors = video_service.load_results(Path("results.json"))
        self.assertIsNone(results)
        self.assertIn("not valid JSON", errors[0])

    def test_missing_file_is_reported(self) -> None:
        results, errors = video_service.load_results(Path("does/not/exist.json"))
        self.assertIsNone(results)
        self.assertIn("not found", errors[0])

    def test_scores_written_with_thousand_separators_are_read(self) -> None:
        payload = {
            "match_id": 1,
            "score_ladys": 200,
            "score_opponent": 100,
            "entries": [{"pid": 1, "score": "43 635", "points": "200"}],
        }
        with mock.patch.object(Path, "read_text", return_value=json.dumps(payload)):
            results, errors = video_service.load_results(Path("results.json"))
        self.assertEqual(errors, [])
        self.assertEqual(results.entries[0].score, 43635)
        self.assertEqual(results.entries[0].points, 200)

    def test_entries_must_be_a_non_empty_list(self) -> None:
        with mock.patch.object(Path, "read_text", return_value=json.dumps({"match_id": 1, "entries": []})):
            _, errors = video_service.load_results(Path("results.json"))
        self.assertIn("entries must be a non-empty list", errors)


class ApplyResultsTests(TemporaryDatabaseTestCase):
    """Match 1 exists with player 1 (active PLTE) scored 50000/200."""

    def results(self, **overrides) -> VideoResults:
        base = dict(
            match_id=1,
            score_ladys=210,
            score_opponent=150,
            entries=[VideoEntry(pid=1, score=44000, points=210)],
            opponent="Rivals",
        )
        base.update(overrides)
        return VideoResults(**base)

    def test_points_sum_must_equal_the_team_total(self) -> None:
        outcome = video_service.apply_results(self.results(score_ladys=999), match_id=1)
        self.assertEqual(outcome.status, "VALIDATION_ERRORS")
        self.assertTrue(any("does not match the team total" in error for error in outcome.errors))

    def test_force_downgrades_the_sum_check_to_a_warning(self) -> None:
        outcome = video_service.apply_results(self.results(score_ladys=999), match_id=1, force=True, dry_run=True)
        self.assertEqual(outcome.status, "DRY_RUN")
        self.assertTrue(any("[forced]" in warning for warning in outcome.warnings))

    def test_unknown_and_duplicate_players_are_rejected(self) -> None:
        entries = [VideoEntry(pid=1, score=100, points=105), VideoEntry(pid=1, score=100, points=105)]
        outcome = video_service.apply_results(self.results(entries=entries), match_id=1)
        self.assertEqual(outcome.status, "VALIDATION_ERRORS")
        self.assertTrue(any("more than once" in error for error in outcome.errors))

        outcome = video_service.apply_results(
            self.results(entries=[VideoEntry(pid=999, score=100, points=210)]), match_id=1
        )
        self.assertTrue(any("does not exist" in error for error in outcome.errors))

    def test_out_of_range_values_are_rejected(self) -> None:
        outcome = video_service.apply_results(
            self.results(score_ladys=210, entries=[VideoEntry(pid=1, score=99999, points=210)]), match_id=1
        )
        self.assertTrue(any("outside 0..75000" in error for error in outcome.errors))

    def test_a_foreign_opponent_blocks_the_import(self) -> None:
        outcome = video_service.apply_results(self.results(opponent="2MuchClutch"), match_id=1)
        self.assertEqual(outcome.status, "VALIDATION_ERRORS")
        self.assertTrue(any("opponent mismatch" in error for error in outcome.errors))

    def test_the_opponent_written_differently_passes(self) -> None:
        outcome = video_service.apply_results(self.results(opponent="RIVALS 🔥"), match_id=1, dry_run=True)
        self.assertEqual(outcome.status, "DRY_RUN")
        self.assertFalse(any("opponent" in warning for warning in outcome.warnings))

    def test_a_missing_opponent_only_warns_that_the_check_was_skipped(self) -> None:
        outcome = video_service.apply_results(self.results(opponent=""), match_id=1, dry_run=True)
        self.assertEqual(outcome.status, "DRY_RUN")
        self.assertTrue(any("wrong-video check was skipped" in warning for warning in outcome.warnings))

    def test_force_downgrades_the_opponent_check(self) -> None:
        outcome = video_service.apply_results(
            self.results(opponent="2MuchClutch"), match_id=1, force=True, dry_run=True
        )
        self.assertEqual(outcome.status, "DRY_RUN")
        self.assertTrue(any("opponent mismatch" in warning for warning in outcome.warnings))

    def test_a_higher_score_with_fewer_points_is_a_misread(self) -> None:
        entries = [
            VideoEntry(pid=1, score=44000, points=100),
            VideoEntry(pid=2, score=40000, points=110),
        ]
        outcome = video_service.apply_results(self.results(entries=entries), match_id=1)
        self.assertEqual(outcome.status, "VALIDATION_ERRORS")
        self.assertTrue(any("is misread" in error for error in outcome.errors))

    def test_equal_points_at_different_scores_are_fine(self) -> None:
        entries = [
            VideoEntry(pid=1, score=44000, points=105),
            VideoEntry(pid=2, score=40000, points=105),
        ]
        outcome = video_service.apply_results(self.results(entries=entries), match_id=1, dry_run=True)
        self.assertEqual(outcome.status, "DRY_RUN")

    def test_score_above_the_events_ceiling_is_rejected(self) -> None:
        # The fixture event allows 4 x 15000 = 60000, well below the global 75000.
        outcome = video_service.apply_results(
            self.results(entries=[VideoEntry(pid=1, score=61000, points=210)]), match_id=1
        )
        self.assertTrue(any("above the 60000" in error for error in outcome.errors))

    def test_unknown_match_is_reported(self) -> None:
        self.assertEqual(video_service.apply_results(self.results(), match_id=404).status, "NO_MATCH")

    def test_dry_run_writes_nothing(self) -> None:
        outcome = video_service.apply_results(self.results(), match_id=1, dry_run=True)
        self.assertEqual(outcome.status, "DRY_RUN")
        self.assertEqual(self.stored_score(), (50000, 200))

    def test_apply_updates_scores_and_the_match_result(self) -> None:
        outcome = video_service.apply_results(self.results(), match_id=1)
        self.assertEqual(outcome.status, "APPLIED")
        self.assertEqual((outcome.imported, outcome.changed, outcome.failed), (1, 1, 0))
        self.assertTrue(outcome.score_updated)
        self.assertEqual(self.stored_score(), (44000, 210))
        self.assertEqual(self.stored_result(), (210, 150))

    def test_roster_players_without_an_entry_are_warned_about(self) -> None:
        outcome = video_service.apply_results(
            VideoResults(match_id=1, score_ladys=0, score_opponent=0, entries=[]), match_id=1
        )
        self.assertTrue(any("without an entry" in warning for warning in outcome.warnings))

    def stored_score(self) -> tuple[int, int]:
        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT score, points FROM matchscore WHERE match_id=1 AND player_id=1").fetchone()

    def stored_result(self) -> tuple[int, int]:
        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT score_ladys, score_opponent FROM match WHERE id=1").fetchone()


class ReviewNoteTests(TemporaryDatabaseTestCase):
    """Match 1: player 1 (Alice, active PLTE) scored 50000/200, opponent 'Rivals'."""

    def notes_for(self, entries, **overrides):
        results = VideoResults(
            match_id=1,
            score_ladys=sum(e.points for e in entries),
            score_opponent=150,
            entries=entries,
            opponent=overrides.get("opponent", "Rivals"),
        )
        outcome = video_service.apply_results(results, match_id=1, dry_run=True)
        self.assertEqual(outcome.status, "DRY_RUN", outcome.errors)
        return {note.kind: note for note in outcome.notes}

    def test_an_ascii_name_change_comes_with_a_ready_made_command(self) -> None:
        notes = self.notes_for([VideoEntry(pid=1, score=44000, points=210, name="Alicia")])
        self.assertIn("name", notes)
        self.assertIn("player edit --id 1 --name 'Alicia'", notes["name"].command)

    def test_a_non_ascii_name_is_reported_but_not_offered_as_a_command(self) -> None:
        notes = self.notes_for([VideoEntry(pid=1, score=44000, points=210, name="Al\u00efc\u00e9\u03c0")])
        self.assertIn("name", notes)
        self.assertEqual(notes["name"].command, "")
        self.assertIn("transliterate", notes["name"].message)

    def test_decoration_only_differences_stay_silent(self) -> None:
        notes = self.notes_for([VideoEntry(pid=1, score=44000, points=210, name="\u2b50 ALICE \U0001f525")])
        self.assertNotIn("name", notes)

    def test_a_zero_row_counts_as_did_not_drive(self) -> None:
        # Player 2 is not PLTE, so only player 1 is on the roster - and drove nothing.
        notes = self.notes_for([VideoEntry(pid=2, score=30000, points=50), VideoEntry(pid=1, score=0, points=0)])
        self.assertIn("missing", notes)
        self.assertIn("Alice", notes["missing"].message)
        self.assertIn("did not drive", notes["missing"].message)

    def add_late_joiner(self, joined_at: str) -> None:
        """A second active PLTE player whose roster row postdates match 1 (2021-06-05)."""
        import sqlite3

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO players (id, name, alias, garage_power, active, team, discord_name,
                                     is_leader, created_at)
                VALUES (3, 'Newbie', 'newbie', 3000, 1, 'PLTE', NULL, 0, ?)
                """,
                (joined_at,),
            )

    def test_a_player_who_joined_after_the_match_started_is_excused(self) -> None:
        self.add_late_joiner("2021-06-09 08:00:00")
        notes = self.notes_for([VideoEntry(pid=1, score=44000, points=210)])
        self.assertIn("joined", notes)
        self.assertIn("Newbie", notes["joined"].message)
        self.assertIn("could not drive it", notes["joined"].message)
        # ...and is not also reported as a plain no-show.
        self.assertNotIn("missing", notes)

    def test_joining_on_the_start_date_itself_stays_a_no_show(self) -> None:
        """Day granularity cannot say whether that was before or after the start."""
        self.add_late_joiner("2021-06-05 08:00:00")
        notes = self.notes_for([VideoEntry(pid=1, score=44000, points=210)])
        self.assertNotIn("joined", notes)
        self.assertIn("Newbie", notes["missing"].message)

    def test_a_player_who_has_driven_before_is_never_excused_by_a_late_roster_date(self) -> None:
        """Guards the bulk `created_at` seed date: Alice's row postdates the 2021 match,
        but her result for it proves she was a member."""
        notes = self.notes_for([VideoEntry(pid=2, score=30000, points=50), VideoEntry(pid=1, score=0, points=0)])
        self.assertNotIn("joined", notes)
        self.assertIn("missing", notes)
        self.assertIn("Alice", notes["missing"].message)

    def test_a_close_opponent_spelling_is_offered_as_a_match_edit(self) -> None:
        notes = self.notes_for(
            [VideoEntry(pid=1, score=44000, points=210)], opponent="Rivalz"
        )
        self.assertIn("opponent", notes)
        self.assertIn("match edit --id 1 --opponent 'Rivalz'", notes["opponent"].command)


if __name__ == "__main__":
    unittest.main()
