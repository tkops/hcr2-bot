from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DistanceEntry:
    id: int
    player_id: int
    year: int
    week: int
    km: int


@dataclass(frozen=True)
class DistanceRankRow:
    """One player in a week's ranking, with their own average for comparison."""

    player_id: int
    name: str
    km: int
    average: float
    weeks: int


@dataclass(frozen=True)
class DistanceHistoryRow:
    year: int
    week: int
    km: int
    rank: int
    of: int


@dataclass(frozen=True)
class DistanceWeek:
    year: int
    week: int
    total: int
    players: int


@dataclass(frozen=True)
class PlayerDistanceSummary:
    average: float
    weeks: int
    last_km: int | None
    last_year: int | None
    last_week: int | None
