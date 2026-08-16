"""Final-standings video -> match scores.

The workbook detour exists because a chat client cannot reach the database; a local
analysis can. So the video is picked up from the same Nextcloud folder as the match
sheets, cut into frames, read, and the readings are applied straight to matchscore.

The one check that decides whether a reading is trustworthy - the sum of the points
column against the team total shown in the video header - is enforced here in code
(``validate_results``) instead of being left to prompt discipline.
"""
from __future__ import annotations

import difflib
import json
import os
import shutil
import statistics
import subprocess
import unicodedata
from pathlib import Path
from typing import Callable, Optional, Sequence

from hcr2.integrations import nextcloud
from hcr2.models.video import (
    ApplyOutcome,
    FramesOutcome,
    PullOutcome,
    ReviewNote,
    RosterPlayer,
    VideoCandidate,
    VideoEntry,
    VideoResults,
)
from hcr2.repositories import matches as match_repo
from hcr2.repositories import matchscores as matchscore_repo
from hcr2.repositories import players as player_repo
from hcr2.services import matchscores as matchscore_service


VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm")

LOCAL_VIDEO_ROOT = Path("tmp") / "video"
TEAM_VIDEO_NAME = "Ladys.mp4"
TEAM_LOCAL_DIR = LOCAL_VIDEO_ROOT / "team"
CHEST_LOCAL_ROOT = LOCAL_VIDEO_ROOT / "chest"
FRAME_PATTERN = "frame_%04d.jpg"
FRAME_GLOB = "frame_*.jpg"

DEFAULT_FPS = 1.0
DEFAULT_WIDTH = 1600

FFMPEG_ENV = "HCR2_FFMPEG"

MAX_SCORE = 75000
MAX_POINTS = 300

# Team names carry emoji, box drawing and mixed case, and the video renders them
# differently from the database. Anything above this similarity counts as the same team.
OPPONENT_SIMILARITY = 0.75
OPPONENT_MIN_STEM = 4

# A rename is only offered as a ready-made command above this similarity.
NAME_SUGGEST_SIMILARITY = 0.5
# How far a player has to sit from the team's own shift before it is worth a look.
OUTLIER_MARGIN = 0.15
MIN_HISTORY_FOR_OUTLIER = 3


def local_dir(match_id: int) -> Path:
    return LOCAL_VIDEO_ROOT / str(match_id)


def frames_dir(match_id: int) -> Path:
    return local_dir(match_id) / "frames"


def results_path(match_id: int) -> Path:
    return local_dir(match_id) / "results.json"


def season_folder(season: int) -> str:
    return nextcloud.remote_path(nextcloud.season_subpath(season))


def team_folder() -> str:
    return nextcloud.remote_path(nextcloud.LADYS_DIR)


def chest_folder(year: int) -> str:
    """One subfolder per year, one file per ISO week: Wochen-Truhe/2026/w34.mp4."""
    return nextcloud.remote_path(nextcloud.CHEST_DIR / str(year))


def chest_video_name(week: int) -> str:
    return f"w{week}.mp4"


def chest_local_dir(year: int, week: int) -> Path:
    return CHEST_LOCAL_ROOT / str(year) / f"w{week:02d}"


# -------------------- Nextcloud lookup --------------------

def list_candidates(
    season: int,
    *,
    lister: Callable[[str], Sequence[nextcloud.RemoteEntry]] = nextcloud.list_directory,
) -> list[VideoCandidate]:
    return list_candidates_in(season_folder(season), lister=lister)


def list_candidates_in(
    folder: str,
    *,
    lister: Callable[[str], Sequence[nextcloud.RemoteEntry]] = nextcloud.list_directory,
) -> list[VideoCandidate]:
    entries = lister(folder)
    candidates = [
        VideoCandidate(
            name=entry.name,
            remote_path=entry.path,
            size=entry.size,
            last_modified=entry.last_modified,
        )
        for entry in entries
        if not entry.is_dir and entry.name.lower().endswith(VIDEO_SUFFIXES)
    ]
    candidates.sort(key=_sort_key, reverse=True)
    return candidates


def _sort_key(candidate: VideoCandidate):
    timestamp = candidate.last_modified
    return (timestamp is not None, timestamp.timestamp() if timestamp is not None else 0.0, candidate.name)


def matches_match_id(name: str, match_id: int) -> bool:
    """``627.mp4`` or ``627_Event_Opponent.mp4`` - same naming as the match sheets."""
    stem = name.rsplit(".", 1)[0]
    return stem == str(match_id) or stem.startswith(f"{match_id}_") or stem.startswith(f"{match_id}-")


def select_candidate(
    match_id: int,
    candidates: Sequence[VideoCandidate],
    *,
    filename: str | None = None,
) -> VideoCandidate | None:
    if filename:
        wanted = filename.strip().lower()
        return next((c for c in candidates if c.name.lower() == wanted), None)

    named = [c for c in candidates if matches_match_id(c.name, match_id)]
    pool = named or list(candidates)
    return pool[0] if pool else None


def pull_video(
    match_id: int,
    *,
    filename: str | None = None,
    lister: Callable[[str], Sequence[nextcloud.RemoteEntry]] = nextcloud.list_directory,
    downloader: Callable[[str, Path], Optional[Path]] = nextcloud.download_file,
) -> PullOutcome:
    match = match_repo.get_match(match_id)
    if match is None:
        return PullOutcome(status="NO_MATCH")

    season = match.season_number
    candidates = list_candidates(season, lister=lister)
    if not candidates:
        return PullOutcome(status="NO_VIDEO", season=season)

    candidate = select_candidate(match_id, candidates, filename=filename)
    if candidate is None:
        return PullOutcome(status="NOT_FOUND", candidates=candidates, season=season)

    target = local_dir(match_id) / candidate.name
    if target.exists() and candidate.size and target.stat().st_size == candidate.size:
        return PullOutcome(status="CACHED", local_path=target, candidate=candidate, candidates=candidates, season=season)

    target.parent.mkdir(parents=True, exist_ok=True)
    downloaded = downloader(candidate.remote_path, target)
    if downloaded is None:
        return PullOutcome(status="DOWNLOAD_FAILED", candidate=candidate, candidates=candidates, season=season)

    return PullOutcome(status="OK", local_path=target, candidate=candidate, candidates=candidates, season=season)


# -------------------- Frames --------------------

def resolve_ffmpeg() -> str | None:
    """ffmpeg is not in the CentOS repos under that name and the EPEL build is codec
    limited, so a user-local binary (pip install --user imageio-ffmpeg) counts too."""
    override = os.environ.get(FFMPEG_ENV)
    if override:
        return override if Path(override).exists() else None

    found = shutil.which("ffmpeg")
    if found:
        return found

    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (RuntimeError, OSError):
        return None


def build_ffmpeg_command(
    video_path: Path,
    out_dir: Path,
    *,
    fps: float = DEFAULT_FPS,
    width: int = DEFAULT_WIDTH,
    crop: str | None = None,
    start: str | None = None,
    duration: str | None = None,
    executable: str = "ffmpeg",
) -> list[str]:
    filters = [f"fps={fps}"]
    if crop:
        filters.append(f"crop={crop}")
    if width:
        filters.append(f"scale={width}:-2")

    command = [executable, "-hide_banner", "-loglevel", "error", "-y"]
    if start:
        command += ["-ss", start]
    command += ["-i", str(video_path)]
    if duration:
        command += ["-t", duration]
    command += ["-vf", ",".join(filters), "-q:v", "2", str(out_dir / FRAME_PATTERN)]
    return command


def extract_frames(
    match_id: int,
    *,
    fps: float = DEFAULT_FPS,
    width: int = DEFAULT_WIDTH,
    crop: str | None = None,
    start: str | None = None,
    duration: str | None = None,
    filename: str | None = None,
    lister: Callable[[str], Sequence[nextcloud.RemoteEntry]] = nextcloud.list_directory,
    downloader: Callable[[str, Path], Optional[Path]] = nextcloud.download_file,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
    ffmpeg_resolver: Callable[[], str | None] = resolve_ffmpeg,
) -> FramesOutcome:
    executable = ffmpeg_resolver()
    if executable is None:
        return FramesOutcome(status="FFMPEG_MISSING")

    pull = pull_video(match_id, filename=filename, lister=lister, downloader=downloader)
    return _cut_frames(
        pull,
        frames_dir(match_id),
        executable=executable,
        fps=fps,
        width=width,
        crop=crop,
        start=start,
        duration=duration,
        runner=runner,
    )


def _cut_frames(
    pull: PullOutcome,
    out_dir: Path,
    *,
    executable: str,
    fps: float,
    width: int,
    crop: str | None,
    start: str | None,
    duration: str | None,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None,
) -> FramesOutcome:
    if pull.status not in ("OK", "CACHED") or pull.local_path is None:
        return FramesOutcome(status="NO_VIDEO", pull=pull)

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob(FRAME_GLOB):
        stale.unlink()

    command = build_ffmpeg_command(
        pull.local_path,
        out_dir,
        fps=fps,
        width=width,
        crop=crop,
        start=start,
        duration=duration,
        executable=executable,
    )
    run = runner or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, check=False))
    completed = run(command)
    if completed.returncode != 0:
        return FramesOutcome(status="FFMPEG_FAILED", pull=pull, detail=(completed.stderr or "").strip())

    frames = sorted(out_dir.glob(FRAME_GLOB))
    if not frames:
        return FramesOutcome(status="NO_FRAMES", frame_dir=out_dir, pull=pull)

    return FramesOutcome(status="OK", frame_dir=out_dir, frame_count=len(frames), pull=pull)


# -------------------- Team video (Ladys.mp4) --------------------

def pull_team_video(
    *,
    filename: str = TEAM_VIDEO_NAME,
    lister: Callable[[str], Sequence[nextcloud.RemoteEntry]] = nextcloud.list_directory,
    downloader: Callable[[str, Path], Optional[Path]] = nextcloud.download_file,
) -> PullOutcome:
    """The team screen is not tied to a season, so it lives next to Ladys.xlsx in the base folder."""
    candidates = list_candidates_in(team_folder(), lister=lister)
    if not candidates:
        return PullOutcome(status="NO_VIDEO")

    wanted = filename.strip().lower()
    candidate = next((c for c in candidates if c.name.lower() == wanted), None)
    if candidate is None:
        return PullOutcome(status="NOT_FOUND", candidates=candidates)

    target = TEAM_LOCAL_DIR / candidate.name
    if target.exists() and candidate.size and target.stat().st_size == candidate.size:
        return PullOutcome(status="CACHED", local_path=target, candidate=candidate, candidates=candidates)

    target.parent.mkdir(parents=True, exist_ok=True)
    if downloader(candidate.remote_path, target) is None:
        return PullOutcome(status="DOWNLOAD_FAILED", candidate=candidate, candidates=candidates)
    return PullOutcome(status="OK", local_path=target, candidate=candidate, candidates=candidates)


def extract_team_frames(
    *,
    fps: float = DEFAULT_FPS,
    width: int = DEFAULT_WIDTH,
    crop: str | None = None,
    start: str | None = None,
    duration: str | None = None,
    filename: str = TEAM_VIDEO_NAME,
    lister: Callable[[str], Sequence[nextcloud.RemoteEntry]] = nextcloud.list_directory,
    downloader: Callable[[str, Path], Optional[Path]] = nextcloud.download_file,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
    ffmpeg_resolver: Callable[[], str | None] = resolve_ffmpeg,
) -> FramesOutcome:
    executable = ffmpeg_resolver()
    if executable is None:
        return FramesOutcome(status="FFMPEG_MISSING")

    pull = pull_team_video(filename=filename, lister=lister, downloader=downloader)
    return _cut_frames(
        pull,
        TEAM_LOCAL_DIR / "frames",
        executable=executable,
        fps=fps,
        width=width,
        crop=crop,
        start=start,
        duration=duration,
        runner=runner,
    )


def pull_chest_video(
    year: int,
    week: int,
    *,
    filename: str | None = None,
    lister: Callable[[str], Sequence[nextcloud.RemoteEntry]] = nextcloud.list_directory,
    downloader: Callable[[str, Path], Optional[Path]] = nextcloud.download_file,
) -> PullOutcome:
    candidates = list_candidates_in(chest_folder(year), lister=lister)
    if not candidates:
        return PullOutcome(status="NO_VIDEO")

    wanted = (filename or chest_video_name(week)).strip().lower()
    # w34.mp4 and w034.mp4 are the same week; do not make the user guess the padding.
    candidate = next(
        (c for c in candidates if c.name.lower() == wanted or _week_of(c.name) == week),
        None,
    )
    if candidate is None:
        return PullOutcome(status="NOT_FOUND", candidates=candidates)

    target = chest_local_dir(year, week) / candidate.name
    if target.exists() and candidate.size and target.stat().st_size == candidate.size:
        return PullOutcome(status="CACHED", local_path=target, candidate=candidate, candidates=candidates)

    target.parent.mkdir(parents=True, exist_ok=True)
    if downloader(candidate.remote_path, target) is None:
        return PullOutcome(status="DOWNLOAD_FAILED", candidate=candidate, candidates=candidates)
    return PullOutcome(status="OK", local_path=target, candidate=candidate, candidates=candidates)


def _week_of(name: str) -> int | None:
    stem = name.rsplit(".", 1)[0].strip().lower()
    if not stem.startswith("w") or not stem[1:].isdigit():
        return None
    return int(stem[1:])


def extract_chest_frames(
    year: int,
    week: int,
    *,
    fps: float = DEFAULT_FPS,
    width: int = DEFAULT_WIDTH,
    crop: str | None = None,
    start: str | None = None,
    duration: str | None = None,
    filename: str | None = None,
    lister: Callable[[str], Sequence[nextcloud.RemoteEntry]] = nextcloud.list_directory,
    downloader: Callable[[str, Path], Optional[Path]] = nextcloud.download_file,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
    ffmpeg_resolver: Callable[[], str | None] = resolve_ffmpeg,
) -> FramesOutcome:
    executable = ffmpeg_resolver()
    if executable is None:
        return FramesOutcome(status="FFMPEG_MISSING")

    pull = pull_chest_video(year, week, filename=filename, lister=lister, downloader=downloader)
    return _cut_frames(
        pull,
        chest_local_dir(year, week) / "frames",
        executable=executable,
        fps=fps,
        width=width,
        crop=crop,
        start=start,
        duration=duration,
        runner=runner,
    )


# -------------------- Roster --------------------

def get_roster(match_id: int | None = None) -> list[RosterPlayer] | None:
    """Without a match id: just the active PLTE list - the chest and team screens
    need the same mapping table but have no match to hang it on."""
    if match_id is not None and match_repo.get_match(match_id) is None:
        return None
    return [
        RosterPlayer(id=row.id, name=row.name, alias=row.alias, away_until=row.away_until)
        for row in player_repo.list_players(active_only=True, team_filter="PLTE", sort_by="name")
    ]


# -------------------- Results file --------------------

def load_results(path: Path) -> tuple[VideoResults | None, list[str]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"results file not found: {path}"]
    except json.JSONDecodeError as e:
        return None, [f"results file is not valid JSON: {e}"]
    except OSError as e:
        return None, [f"results file unreadable: {type(e).__name__}: {e}"]

    if not isinstance(payload, dict):
        return None, ["results file must contain one JSON object"]

    errors: list[str] = []
    entries: list[VideoEntry] = []
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        errors.append("entries must be a non-empty list")
        raw_entries = []

    for index, raw in enumerate(raw_entries, start=1):
        if not isinstance(raw, dict):
            errors.append(f"entry {index}: not an object")
            continue
        pid = _as_int(raw.get("pid"))
        score = _as_int(raw.get("score"))
        points = _as_int(raw.get("points"))
        if pid is None or score is None or points is None:
            errors.append(f"entry {index}: pid, score and points must be whole numbers")
            continue
        entries.append(
            VideoEntry(
                pid=pid,
                score=score,
                points=points,
                absent=_as_int(raw.get("absent")),
                checkin=_as_int(raw.get("checkin")) or 0,
                note=str(raw.get("note") or ""),
                name=str(raw.get("name") or "").strip(),
                rank=_as_int(raw.get("rank")),
            )
        )

    results = VideoResults(
        match_id=_as_int(payload.get("match_id")) or 0,
        score_ladys=_as_int(payload.get("score_ladys")) or 0,
        score_opponent=_as_int(payload.get("score_opponent")) or 0,
        entries=entries,
        opponent=str(payload.get("opponent") or "").strip(),
        event=str(payload.get("event") or "").strip(),
    )
    return results, errors


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace(" ", "").replace(".", "").replace("_", "")
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def normalize_team_name(value: str) -> str:
    """Strip everything the video renders differently: case, spaces, accents, emoji, symbols."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch for ch in without_marks.lower() if ch.isalnum())


def compare_opponent(read: str, stored: str) -> tuple[str, float]:
    """Second independent proof that this is the right recording, next to the points sum.

    Returns (verdict, similarity) with verdict in MATCH / CLOSE / MISMATCH / UNCOMPARABLE.
    """
    read_key = normalize_team_name(read)
    stored_key = normalize_team_name(stored)
    if not read_key or not stored_key:
        return "UNCOMPARABLE", 0.0
    if read_key == stored_key:
        return "MATCH", 1.0

    similarity = difflib.SequenceMatcher(None, read_key, stored_key).ratio()
    if similarity >= OPPONENT_SIMILARITY:
        return "CLOSE", similarity

    # The video header truncates long team names, which drags the ratio down although
    # what is readable matches exactly.
    shorter, longer = sorted((read_key, stored_key), key=len)
    if len(shorter) >= OPPONENT_MIN_STEM and shorter in longer:
        return "CLOSE", similarity

    return "MISMATCH", similarity


def _check_opponent(results: VideoResults, stored: str, *, force: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not results.opponent:
        warnings.append(
            "opponent not read from the video header - the wrong-video check was skipped"
        )
        return errors, warnings

    verdict, similarity = compare_opponent(results.opponent, stored)
    if verdict == "MATCH":
        return errors, warnings
    if verdict == "UNCOMPARABLE":
        warnings.append(
            f"opponent '{results.opponent}' vs '{stored}': nothing comparable left after "
            "normalisation - check by eye"
        )
        return errors, warnings
    if verdict == "CLOSE":
        warnings.append(
            f"opponent reads as '{results.opponent}', stored is '{stored}' "
            f"({similarity:.0%} similar) - taken as the same team"
        )
        return errors, warnings

    message = (
        f"opponent mismatch: video says '{results.opponent}', match {results.match_id or '?'} "
        f"is against '{stored}' ({similarity:.0%} similar) - wrong video or wrong match id"
    )
    if force:
        warnings.append(message + " [forced]")
    else:
        errors.append(message)
    return errors, warnings


def _check_monotonicity(rows: Sequence[tuple[VideoEntry, str]]) -> list[str]:
    """The standings are ordered by score, and points follow the rank. So a higher score
    can never carry fewer points - if it does, a digit was misread."""
    scored = sorted([row for row in rows if row[0].score > 0], key=lambda row: -row[0].score)
    errors = []
    for (upper, upper_name), (lower, lower_name) in zip(scored, scored[1:]):
        if lower.points > upper.points:
            errors.append(
                f"{lower_name} ({lower.pid}) has {lower.points} points at score {lower.score}, "
                f"but {upper_name} ({upper.pid}) only {upper.points} at the higher score "
                f"{upper.score} - one of the two rows is misread"
            )
    return errors


def _check_ceiling(rows: Sequence[tuple[VideoEntry, str]], match_id: int) -> list[str]:
    ceiling = matchscore_repo.get_match_score_ceiling(match_id)
    if not ceiling:
        return []
    return [
        f"{name} ({entry.pid}): score {entry.score} is above the {ceiling} this event allows "
        f"(tracks x max score per track)"
        for entry, name in rows
        if entry.score > ceiling
    ]


def _check_event(results: VideoResults, stored: str) -> list[str]:
    """Same idea as the opponent check, one level up: the event title sits in the video header."""
    if not results.event:
        return []
    verdict, similarity = compare_opponent(results.event, stored)
    if verdict in ("MATCH", "UNCOMPARABLE"):
        return []
    if verdict == "CLOSE":
        return [f"event reads as '{results.event}', stored is '{stored}' ({similarity:.0%} similar)"]
    return [
        f"event mismatch: video says '{results.event}', match is '{stored}' "
        f"({similarity:.0%} similar) - check the match id"
    ]


def validate_results(
    results: VideoResults,
    *,
    match_id: int,
    force: bool = False,
) -> tuple[list[str], list[str], list[tuple[VideoEntry, str]]]:
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[tuple[VideoEntry, str]] = []

    if results.match_id and results.match_id != match_id:
        errors.append(f"results file is for match {results.match_id}, not {match_id}")

    match = match_repo.get_match(match_id)
    if match is not None:
        opponent_errors, opponent_warnings = _check_opponent(results, match.opponent, force=force)
        errors.extend(opponent_errors)
        warnings.extend(opponent_warnings)
        warnings.extend(_check_event(results, match.event_name))

    if results.score_ladys <= 0:
        errors.append("score_ladys is missing - it is the team total from the video header")
    if results.score_opponent <= 0:
        warnings.append("score_opponent is 0 - was the opponent total unreadable?")

    seen: set[int] = set()
    for entry in results.entries:
        if entry.pid in seen:
            errors.append(f"player {entry.pid} appears more than once")
            continue
        seen.add(entry.pid)

        brief = player_repo.get_player_brief(entry.pid)
        if brief is None:
            errors.append(f"player {entry.pid} does not exist")
            continue
        if not 0 <= entry.score <= MAX_SCORE:
            errors.append(f"player {entry.pid} ({brief.name}): score {entry.score} outside 0..{MAX_SCORE}")
        if not 0 <= entry.points <= MAX_POINTS:
            errors.append(f"player {entry.pid} ({brief.name}): points {entry.points} outside 0..{MAX_POINTS}")
        rows.append((entry, brief.name))

    monotonicity_errors = _check_monotonicity(rows) + _check_ceiling(rows, match_id)
    if force:
        warnings.extend(message + " [forced]" for message in monotonicity_errors)
    else:
        errors.extend(monotonicity_errors)

    points_total = sum(entry.points for entry in results.entries)
    if points_total != results.score_ladys:
        difference = points_total - results.score_ladys
        message = (
            f"points sum {points_total} does not match the team total {results.score_ladys} "
            f"from the video header (off by {difference:+d}) - a row was missed or misread"
        )
        if force:
            warnings.append(message + " [forced]")
        else:
            errors.append(message)

    # Who is missing is spelled out per player in build_notes, away-aware - here only the count.
    missing = len([player for player in get_roster(match_id) or [] if player.id not in seen])
    if missing:
        warnings.append(f"{missing} roster player(s) without an entry - see the review below")

    return errors, warnings, rows


# -------------------- Review: what does not fit --------------------

def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _thousands(value: float) -> str:
    """Same grouping the game uses in the video: 43 635, not 43,635."""
    return f"{value:,.0f}".replace(",", " ")


def _name_notes(rows: Sequence[tuple[VideoEntry, str]]) -> list[ReviewNote]:
    """A name that survives normalisation differently is either a rename or a stored typo."""
    notes = []
    for entry, stored in rows:
        if not entry.name:
            continue
        verdict, similarity = compare_opponent(entry.name, stored)
        if verdict in ("MATCH", "UNCOMPARABLE"):
            continue

        message = f"{stored} ({entry.pid}) reads as '{entry.name}' in the video ({similarity:.0%} similar)"
        # Only offer the edit when the video name is typeable on the German keyboard the
        # team uses - everything else has to be transliterated by hand first.
        command = ""
        if entry.name.isascii() and similarity >= NAME_SUGGEST_SIMILARITY:
            command = f"python3 hcr2.py player edit --id {entry.pid} --name {_quote(entry.name)}"
        elif not entry.name.isascii():
            message += " - transliterate before applying"
        notes.append(ReviewNote(kind="name", message=message, command=command))
    return notes


def _absence_notes(match_id: int, rows: Sequence[tuple[VideoEntry, str]]) -> list[ReviewNote]:
    """A 0/0 row and a missing row mean the same thing - the player did not drive."""
    drove = {entry.pid for entry, _ in rows if entry.score > 0 or entry.points > 0}

    notes = []
    for player in get_roster(match_id) or []:
        if player.id in drove:
            continue
        history = matchscore_repo.recent_scores(player.id, exclude_match_id=match_id)
        last = f", last scored {_thousands(history[0])}" if history else ", no earlier score"
        if matchscore_service.compute_absent(match_id, player.id):
            notes.append(ReviewNote(
                kind="absent",
                message=f"{player.name} ({player.id}) did not drive - marked away, so expected{last}",
            ))
            continue
        notes.append(ReviewNote(
            kind="missing",
            message=f"{player.name} ({player.id}) did not drive and is not marked away{last}",
        ))
    return notes


def _outlier_notes(match_id: int, rows: Sequence[tuple[VideoEntry, str]]) -> list[ReviewNote]:
    """Measured against the team's own shift, not against the player's average alone -
    a hard track set drags everyone down and would otherwise flag the whole roster."""
    deviations = []
    for entry, name in rows:
        if entry.score <= 0:
            continue
        history = matchscore_repo.recent_scores(entry.pid, exclude_match_id=match_id)
        if len(history) < MIN_HISTORY_FOR_OUTLIER:
            continue
        average = sum(history) / len(history)
        if average <= 0:
            continue
        deviations.append(((entry.score - average) / average, entry, name, average))

    if len(deviations) < MIN_HISTORY_FOR_OUTLIER:
        return []

    median = statistics.median(deviation for deviation, _, _, _ in deviations)
    notes = []
    for deviation, entry, name, average in sorted(deviations):
        relative = deviation - median
        if abs(relative) < OUTLIER_MARGIN:
            continue
        notes.append(ReviewNote(
            kind="outlier",
            message=(
                f"{name} ({entry.pid}): {_thousands(entry.score)} is {relative:+.0%} off their usual "
                f"{_thousands(average)} (team as a whole {median:+.0%}) - misread or a real slump?"
            ),
        ))
    return notes


def build_notes(
    results: VideoResults,
    *,
    match_id: int,
    rows: Sequence[tuple[VideoEntry, str]],
) -> list[ReviewNote]:
    notes: list[ReviewNote] = []
    match = match_repo.get_match(match_id)

    if match is not None and results.opponent:
        verdict, _ = compare_opponent(results.opponent, match.opponent)
        if verdict == "CLOSE":
            notes.append(ReviewNote(
                kind="opponent",
                message=f"opponent is stored as '{match.opponent}', the video shows '{results.opponent}'",
                command=f"python3 hcr2.py match edit --id {match_id} --opponent {_quote(results.opponent)}",
            ))

    notes.extend(_name_notes(rows))
    notes.extend(_absence_notes(match_id, rows))
    notes.extend(_outlier_notes(match_id, rows))
    return notes


def apply_results(
    results: VideoResults,
    *,
    match_id: int,
    force: bool = False,
    dry_run: bool = False,
) -> ApplyOutcome:
    if match_repo.get_match(match_id) is None:
        return ApplyOutcome(status="NO_MATCH")

    errors, warnings, rows = validate_results(results, match_id=match_id, force=force)
    if errors:
        return ApplyOutcome(status="VALIDATION_ERRORS", errors=errors, warnings=warnings, results=results, rows=rows)

    notes = build_notes(results, match_id=match_id, rows=rows)

    if dry_run:
        return ApplyOutcome(status="DRY_RUN", warnings=warnings, results=results, rows=rows, notes=notes)

    imported = 0
    changed = 0
    failed = 0
    failures: list[str] = []

    # Not apply_match_sheet_entries: absent may be left out here, and then it has to be
    # derived from the away dates instead of being forced to 0.
    for entry, name in rows:
        result = matchscore_service.add_score(
            match_id=match_id,
            player_input=str(entry.pid),
            score=entry.score,
            points=entry.points,
            absent_override=entry.absent,
            checkin_override=entry.checkin,
        )
        if result.status in ("CHANGED", "UNCHANGED"):
            imported += 1
            if result.status == "CHANGED":
                changed += 1
        else:
            failed += 1
            failures.append(f"player {entry.pid} ({name}): {result.status}")

    score_updated = match_repo.update_match(
        match_id,
        {"score_ladys": results.score_ladys, "score_opponent": results.score_opponent},
    ) > 0

    return ApplyOutcome(
        status="APPLIED",
        errors=failures,
        warnings=warnings,
        results=results,
        rows=rows,
        notes=notes,
        imported=imported,
        changed=changed,
        failed=failed,
        score_updated=score_updated,
    )
