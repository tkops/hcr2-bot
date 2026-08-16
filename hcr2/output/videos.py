from __future__ import annotations

from collections.abc import Sequence

from hcr2.models.video import (
    ApplyOutcome,
    FramesOutcome,
    PullOutcome,
    ReviewNote,
    RosterPlayer,
    VideoCandidate,
)
from hcr2.output.tables import print_table
from hcr2.services.videos import matches_match_id


FFMPEG_HINT = "pip3 install --user imageio-ffmpeg (no root needed), or set HCR2_FFMPEG=/path/to/ffmpeg"


def print_no_match_found() -> None:
    print("❌ No match found.")


def print_invalid_match_id() -> None:
    print("❌ Invalid match id.")


def print_no_video_found(folder: str, *, match_id: int) -> None:
    print(f"❌ No video found in {folder}")
    print(f"   Put the recording there, ideally named after the match (e.g. {match_id}.mp4).")


def print_team_video_missing(folder: str, filename: str) -> None:
    print(f"❌ '{filename}' not found in {folder}")
    print("   Upload the team screen recording there, next to Ladys.xlsx.")


def print_video_not_found(filename: str, candidates: Sequence[VideoCandidate]) -> None:
    print(f"❌ Video '{filename}' not found on Nextcloud")
    print_candidates(candidates)


def print_download_failed(name: str) -> None:
    print(f"❌ Download of '{name}' failed")


def print_candidates(candidates: Sequence[VideoCandidate]) -> None:
    if not candidates:
        return
    print_table(
        headers=[f"{'Video':<40}", f"{'Size':>10}", "Modified"],
        rows=[
            [f"{c.name:<40}", f"{_mb(c.size):>10}", c.last_modified.strftime("%Y-%m-%d %H:%M") if c.last_modified else "-"]
            for c in candidates
        ],
        width=70,
    )


def print_pull_outcome(outcome: PullOutcome, *, match_id: int) -> None:
    candidate = outcome.candidate
    if candidate is None or outcome.local_path is None:
        return
    state = "Cached" if outcome.status == "CACHED" else "Downloaded"
    print(f"✅ {candidate.name} ({_mb(candidate.size)}) → {outcome.local_path} ({state})")
    print_ambiguity_warning(outcome, match_id=match_id)


def print_ambiguity_warning(outcome: PullOutcome, *, match_id: int) -> None:
    """A wrong video means wrong scores, so say so whenever the name does not prove the match."""
    candidate = outcome.candidate
    if candidate is None or matches_match_id(candidate.name, match_id):
        return

    others = [c.name for c in outcome.candidates if c.name != candidate.name]
    if others:
        print(f"⚠️  '{candidate.name}' does not name match {match_id}; picked the newest of {len(outcome.candidates)}"
              f" videos, also present: {', '.join(others)}")
    else:
        print(f"⚠️  '{candidate.name}' does not name match {match_id} - check it is the right recording.")
    print(f"   Name the file {match_id}.mp4 or pass --file <name> to be explicit.")


def print_frames_outcome(outcome: FramesOutcome) -> None:
    if outcome.status == "FFMPEG_MISSING":
        print(f"❌ ffmpeg not found - {FFMPEG_HINT}")
        return
    if outcome.status == "FFMPEG_FAILED":
        print("❌ ffmpeg failed")
        if outcome.detail:
            for line in outcome.detail.splitlines()[:5]:
                print(f"   {line}")
        return
    if outcome.status == "NO_FRAMES":
        print(f"❌ ffmpeg produced no frames in {outcome.frame_dir}")
        return
    print(f"✅ {outcome.frame_count} frames → {outcome.frame_dir}")


def print_roster(match_id: int | None, roster: Sequence[RosterPlayer]) -> None:
    scope = f"match {match_id}" if match_id is not None else "the active team"
    print(f"Roster for {scope} - {len(roster)} active PLTE players")
    print_table(
        headers=[f"{'ID':>4}", f"{'Player':<24}", f"{'Alias':<16}", "Away until"],
        rows=[
            [f"{player.id:>4}", f"{player.name:<24}", f"{(player.alias or '-'):<16}", player.away_until or "-"]
            for player in roster
        ],
        width=60,
    )


def print_results_errors(errors: Sequence[str]) -> None:
    print("❌ Import aborted due to validation errors:")
    for message in errors:
        print(" -", message)


def print_warnings(warnings: Sequence[str]) -> None:
    for message in warnings:
        print(f"⚠️  {message}")


NOTE_LABELS = {
    "opponent": "Opponent",
    "name": "Name",
    "missing": "Not in standings",
    "absent": "Away",
    "outlier": "Score",
}


def print_notes(notes: Sequence[ReviewNote]) -> None:
    """Suggestions, not verdicts - none of this blocks the import."""
    if not notes:
        return
    print()
    print(f"🔎 {len(notes)} thing(s) to look at:")
    for note in notes:
        print(f"   [{NOTE_LABELS.get(note.kind, note.kind)}] {note.message}")
        if note.command:
            print(f"      → {note.command}")


def print_apply_outcome(outcome: ApplyOutcome, *, match_id: int) -> None:
    if outcome.status == "NO_MATCH":
        print_no_match_found()
        return
    if outcome.status == "VALIDATION_ERRORS":
        print_results_errors(outcome.errors)
        print_warnings(outcome.warnings)
        return

    print_entry_table(outcome)
    print_warnings(outcome.warnings)

    results = outcome.results
    if outcome.status == "DRY_RUN":
        total = sum(entry.points for entry, _ in outcome.rows)
        print(
            f"ℹ️  Dry run: {len(outcome.rows)} entries, points sum {total} "
            f"= team total {results.score_ladys if results else 0}. Nothing written."
        )
        print_notes(outcome.notes)
        return

    score_status = "Score updated" if outcome.score_updated else "Score update failed"
    print(
        f"✅ Match {match_id}: {outcome.imported} imported, {outcome.changed} changed, "
        f"{outcome.failed} failed; {score_status}"
    )
    for message in outcome.errors:
        print(f"❌ {message}")
    print_notes(outcome.notes)


def print_entry_table(outcome: ApplyOutcome) -> None:
    if not outcome.rows:
        return
    print_table(
        headers=[f"{'ID':>4}", f"{'Player':<24}", f"{'Score':>7}", f"{'Points':>6}", f"{'Abs':>3}", f"{'Chk':>3}", "Note"],
        rows=[
            [
                f"{entry.pid:>4}",
                f"{name:<24}",
                f"{entry.score:>7}",
                f"{entry.points:>6}",
                f"{('-' if entry.absent is None else entry.absent):>3}",
                f"{entry.checkin:>3}",
                entry.note,
            ]
            for entry, name in outcome.rows
        ],
        width=60,
    )


def _mb(size: int) -> str:
    if not size:
        return "-"
    return f"{size / (1024 * 1024):.1f} MB"
