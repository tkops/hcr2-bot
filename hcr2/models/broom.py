"""Row and result shapes for the broom ranking."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BroomWindowRow:
    """One matchscore inside the window, joined with what is needed to judge it."""

    match_id: int
    player_id: int
    start: str
    score: int
    points: int
    absent: int | None
    checkin: int | None
    tracks: int | None


@dataclass(frozen=True)
class RosterMember:
    player_id: int
    name: str
    garage_power: int
    is_leader: bool


@dataclass(frozen=True)
class BroomFactor:
    """One weighted axis. ``value`` is 0..1 where 1 is the worst possible."""

    key: str
    label: str
    weight: int
    value: float | None          # None: not enough data, weight is redistributed

    @property
    def rated(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class BroomCandidate:
    player_id: int
    name: str
    garage_power: int
    risk: float                  # 0..100, already multiplied by ``loyalty``
    raw_risk: float              # before the loyalty shield
    loyalty: float               # protective multiplier 0.6..1.0
    driven_total: int            # matches driven ever - what loyalty is measured on
    window_rows: int
    window_driven: int
    unexcused: int
    excused: int
    blocker_episodes: int
    blockers_earlier: int
    km_average: float | None
    km_weeks: int
    km_rank: int | None
    performance: float | None    # GP-corrected delta to the match median
    raw_delta: float | None      # same without the GP correction
    points_total: int            # event points earned inside the window
    points_per_row: float | None # per roster match, absences counted as zero
    points_rank: int | None      # 1 = contributed least
    drops: int
    worst_drop: float | None
    matches_since_driven: int | None
    probation: bool              # first matches for the team: no weakness allowed
    returner: bool               # history outside the window - coming back is loyalty
    immediate: bool              # veto rule tripped - ranked above everything else
    factors: list[BroomFactor] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BroomUnrated:
    """Only for a player with no roster row in the window at all - there is nothing
    to measure. Everybody who was in a match gets rated."""

    player_id: int
    name: str
    window_driven: int
    driven_total: int
    reason: str


@dataclass(frozen=True)
class BroomResult:
    status: str
    window: int = 0
    matches: int = 0
    candidates: list[BroomCandidate] = field(default_factory=list)
    unrated: list[BroomUnrated] = field(default_factory=list)
    cohort_size: int = 0         # players with MIN_MATCHES driven - the yardstick
    gp_slope: float = 0.0
    team_unexcused_rate: float = 0.0
    team_km_average: float = 0.0
    leaders_skipped: int = 0
