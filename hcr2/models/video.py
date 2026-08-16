from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class VideoCandidate:
    """One video file lying next to the match sheets on Nextcloud."""

    name: str
    remote_path: str
    size: int
    last_modified: datetime | None


@dataclass(frozen=True)
class VideoEntry:
    """One result row read from the final standings video.

    ``name`` is what the video showed, not what the database holds - the comparison
    between the two is what turns a reading into a rename suggestion.
    """

    pid: int
    score: int
    points: int
    absent: int | None = None
    checkin: int = 0
    note: str = ""
    name: str = ""
    rank: int | None = None


@dataclass(frozen=True)
class VideoResults:
    match_id: int
    score_ladys: int
    score_opponent: int
    entries: list[VideoEntry] = field(default_factory=list)
    opponent: str = ""
    event: str = ""


@dataclass(frozen=True)
class ReviewNote:
    """Something that does not fit, with the command that would fix it."""

    kind: str
    message: str
    command: str = ""


@dataclass(frozen=True)
class RosterPlayer:
    id: int
    name: str
    alias: str | None
    away_until: str | None


@dataclass(frozen=True)
class PullOutcome:
    status: str
    local_path: Path | None = None
    candidate: VideoCandidate | None = None
    candidates: list[VideoCandidate] = field(default_factory=list)
    season: int | None = None


@dataclass(frozen=True)
class FramesOutcome:
    status: str
    frame_dir: Path | None = None
    frame_count: int = 0
    pull: PullOutcome | None = None
    detail: str = ""


@dataclass(frozen=True)
class ApplyOutcome:
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    results: VideoResults | None = None
    rows: list[tuple[VideoEntry, str]] = field(default_factory=list)
    notes: list[ReviewNote] = field(default_factory=list)
    imported: int = 0
    changed: int = 0
    failed: int = 0
    score_updated: bool = False
