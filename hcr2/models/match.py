from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchSummary:
    id: int
    start: str
    event_name: str
    opponent: str


@dataclass(frozen=True)
class MatchDetail:
    id: int
    start: str
    season_number: int
    opponent: str
    event_name: str
    score_ladys: int
    score_opponent: int

