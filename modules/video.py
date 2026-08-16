#!/usr/bin/env python3
"""CLI adapter for the final-standings video pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from hcr2.output import videos as video_output
from hcr2.repositories import matches as match_repo
from hcr2.services import videos as video_service
from modules.common import (
    get_arg_value,
    is_help_request,
    parse_int,
    print_command_help,
    print_unknown_command,
)


USAGE_LIST = "Usage: video list --match <match_id>"
USAGE_PULL = "Usage: video pull --match <match_id> [--file <name>]"
USAGE_FRAMES = (
    "Usage: video frames --match <match_id> [--file <name>] [--fps <n>] "
    "[--width <px>] [--crop <w:h:x:y>] [--start <hh:mm:ss>] [--duration <sec>]"
)
USAGE_ROSTER = "Usage: video roster --match <match_id>"
USAGE_APPLY = "Usage: video apply --match <match_id> [--file <results.json>] [--dry-run] [--force]"


def print_help():
    print_command_help(
        usage="hcr2.py video <command> [options]",
        commands=[
            ("list --match <match_id>", "List video files in the match's season folder"),
            ("pull --match <match_id> [--file <name>]", "Download the match video from Nextcloud"),
            (
                "frames --match <match_id> [--fps <n>] [--width <px>] [--crop <w:h:x:y>]",
                "Cut the video into frames with ffmpeg",
            ),
            ("roster --match <match_id>", "Show active PLTE players for name matching"),
            (
                "apply --match <match_id> [--file <results.json>] [--dry-run] [--force]",
                "Validate readings and write them to matchscore",
            ),
        ],
        notes=[
            "Videos live next to the match sheets: Power-Ladys-Scores/S<season>/.",
            "apply refuses to write unless the points sum equals score_ladys (--force overrides).",
        ],
    )


def handle_command(command, args):
    if is_help_request(command, *args):
        print_help()
        return

    handlers: dict[str, Callable[[list[str]], None]] = {
        "list": _handle_list,
        "pull": _handle_pull,
        "frames": _handle_frames,
        "roster": _handle_roster,
        "apply": _handle_apply,
    }
    handler = handlers.get(command)
    if handler is None:
        print_unknown_command("video", command)
        print_help()
        return
    handler(args)


def _match_id_from(args, usage: str):
    raw = get_arg_value(args, "match")
    if raw is None:
        print(usage)
        return None
    match_id = parse_int(raw, default=None)
    if match_id is None:
        video_output.print_invalid_match_id()
        return None
    return match_id


def _handle_list(args):
    match_id = _match_id_from(args, USAGE_LIST)
    if match_id is None:
        return

    match = match_repo.get_match(match_id)
    if match is None:
        video_output.print_no_match_found()
        return

    folder = video_service.season_folder(match.season_number)
    candidates = video_service.list_candidates(match.season_number)
    if not candidates:
        video_output.print_no_video_found(folder, match_id=match_id)
        return
    video_output.print_candidates(candidates)


def _handle_pull(args):
    match_id = _match_id_from(args, USAGE_PULL)
    if match_id is None:
        return
    outcome = video_service.pull_video(match_id, filename=get_arg_value(args, "file"))
    _report_pull(outcome, match_id=match_id, filename=get_arg_value(args, "file"))


def _report_pull(outcome, *, match_id: int, filename: str | None) -> bool:
    if outcome.status == "NO_MATCH":
        video_output.print_no_match_found()
        return False
    if outcome.status == "NO_VIDEO":
        video_output.print_no_video_found(video_service.season_folder(outcome.season or 0), match_id=match_id)
        return False
    if outcome.status == "NOT_FOUND":
        video_output.print_video_not_found(filename or "", outcome.candidates)
        return False
    if outcome.status == "DOWNLOAD_FAILED":
        video_output.print_download_failed(outcome.candidate.name if outcome.candidate else "?")
        return False

    video_output.print_pull_outcome(outcome, match_id=match_id)
    return True


def _handle_frames(args):
    match_id = _match_id_from(args, USAGE_FRAMES)
    if match_id is None:
        return

    filename = get_arg_value(args, "file")
    fps = _parse_fps(get_arg_value(args, "fps"))
    if fps is None:
        print(USAGE_FRAMES)
        return

    outcome = video_service.extract_frames(
        match_id,
        fps=fps,
        width=parse_int(get_arg_value(args, "width"), default=video_service.DEFAULT_WIDTH),
        crop=get_arg_value(args, "crop"),
        start=get_arg_value(args, "start"),
        duration=get_arg_value(args, "duration"),
        filename=filename,
    )
    if outcome.status == "NO_VIDEO" and outcome.pull is not None:
        _report_pull(outcome.pull, match_id=match_id, filename=filename)
        return
    if outcome.pull is not None:
        video_output.print_pull_outcome(outcome.pull, match_id=match_id)
    video_output.print_frames_outcome(outcome)


def _parse_fps(raw: str | None):
    if raw is None:
        return video_service.DEFAULT_FPS
    try:
        fps = float(raw)
    except ValueError:
        return None
    return fps if fps > 0 else None


def _handle_roster(args):
    match_id = _match_id_from(args, USAGE_ROSTER)
    if match_id is None:
        return
    roster = video_service.get_roster(match_id)
    if roster is None:
        video_output.print_no_match_found()
        return
    video_output.print_roster(match_id, roster)


def _handle_apply(args):
    match_id = _match_id_from(args, USAGE_APPLY)
    if match_id is None:
        return

    raw_file = get_arg_value(args, "file")
    path = Path(raw_file) if raw_file else video_service.results_path(match_id)
    results, read_errors = video_service.load_results(path)
    if results is None or read_errors:
        video_output.print_results_errors(read_errors)
        return

    outcome = video_service.apply_results(
        results,
        match_id=match_id,
        force=get_arg_value(args, "force") is not None,
        dry_run=get_arg_value(args, "dry-run") is not None,
    )
    video_output.print_apply_outcome(outcome, match_id=match_id)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2 or sys.argv[1] != "video":
        print_help()
    else:
        handle_command(sys.argv[2] if len(sys.argv) > 2 else "", sys.argv[3:])
