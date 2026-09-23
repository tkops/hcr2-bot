"""Facts about one finished match, as a model - never as prose.

The recap text that goes into the team chat is written by the model reading this,
not by code: it should read differently every time. What must *not* change between
two runs is the substance, so everything the text may claim is measured here first.

The shapes carry the comparison alongside the number (`podiums_in_window` next to
`window`, `previous_best` next to `score`), because a number without its yardstick
is what turns "zum vierten Mal aufs Treppchen" into a guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PodiumEntry:
    """One of the top three, plus how unusual it is to stand there."""

    rank: int
    player_id: int
    name: str
    score: int
    points: int
    # How often this player was in the top three over the `window` matches before this one.
    podiums_in_window: int
    window: int
    # Matches since the last podium; None when there was none in the window.
    matches_since_last: int | None
    # First podium in the whole history, not only in the window.
    first_ever: bool
    # Matches driven before this one - a podium in the fourth match is a different
    # sentence than one in the four-hundredth.
    matches_played: int
    # Still in the first matches for the team (see NEWCOMER_MATCHES).
    is_newcomer: bool
    # Rare enough to be worth a sentence of its own (see RARE_PODIUM_SHARE).
    notable: bool


@dataclass(frozen=True)
class ImprovementEntry:
    """Drove clearly better than their own recent average, measured against team pace."""

    player_id: int
    name: str
    score: int
    baseline: int
    basis_matches: int
    # score/baseline divided by the team's median of the same ratio: 1.0 means this
    # player moved exactly with the team, above that they gained on it.
    ratio: float
    # Distance to this match's median score - tells a peak apart from a recovery.
    vs_match_median: int


@dataclass(frozen=True)
class RecordEntry:
    player_id: int
    name: str
    score: int
    previous_best: int
    matches_played: int


@dataclass(frozen=True)
class AbsentEntry:
    player_id: int
    name: str
    # away | checkin | no-show
    reason: str


@dataclass(frozen=True)
class EventMatch:
    """A match of the same team event - the only fair yardstick for a team total.

    Score sums are not comparable across events (the tracks differ: 2.27M in one
    event, 1.62M in the next), inside one event they are.
    """

    match_id: int
    start: str
    opponent: str
    score_ladys: int
    score_opponent: int
    total_score: int
    drivers: int
    is_current: bool


@dataclass(frozen=True)
class OpponentMeeting:
    match_id: int
    start: str
    score_ladys: int
    score_opponent: int


@dataclass(frozen=True)
class MatchRecap:
    status: str
    match_id: int
    start: str = ""
    season_number: int = 0
    event_name: str = ""
    tracks: int = 0
    opponent: str = ""
    score_ladys: int = 0
    score_opponent: int = 0
    # WIN | LOSS | DRAW
    result: str = ""
    margin: int = 0
    position_in_event: int = 0
    matches_in_event: int = 0
    total_score: int = 0
    median_score: int = 0
    best_score: int = 0
    roster_rows: int = 0
    drivers: int = 0
    everyone_drove: bool = False
    absent: list[AbsentEntry] = field(default_factory=list)
    podium: list[PodiumEntry] = field(default_factory=list)
    improvements: list[ImprovementEntry] = field(default_factory=list)
    records: list[RecordEntry] = field(default_factory=list)
    event_matches: list[EventMatch] = field(default_factory=list)
    opponent_history: list[OpponentMeeting] = field(default_factory=list)
    season_wins: int = 0
    season_matches: int = 0
    notes: list[str] = field(default_factory=list)
