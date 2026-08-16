from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RosterReading:
    """One row of the team screen, plus whatever decision the user has made about it."""

    name: str
    garage_power: int
    rank: int | None = None
    leader: int | None = None
    pid: int | None = None
    reactivate: int | None = None
    new: bool = False
    note: str = ""


@dataclass(frozen=True)
class RosterVideo:
    players: list[RosterReading] = field(default_factory=list)
    team: str = ""
    member_count: int | None = None


@dataclass(frozen=True)
class RosterCandidate:
    """A player who might be the one standing in the video - active or long gone."""

    player_id: int
    name: str
    team: str | None
    active: int
    garage_power: int
    similarity: float
    last_match: str | None = None


@dataclass(frozen=True)
class PendingAddition:
    reading: RosterReading
    candidates: list[RosterCandidate] = field(default_factory=list)


@dataclass(frozen=True)
class RosterChange:
    kind: str
    name: str
    detail: str
    player_id: int | None = None
    status: str = ""
    # The name as read from the video - a rename changes `name`, so this is what ties
    # the change back to its row in the roster file.
    reading_name: str = ""


@dataclass(frozen=True)
class RosterPlan:
    status: str
    changes: list[RosterChange] = field(default_factory=list)
    pending: list[PendingAddition] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unchanged: int = 0
