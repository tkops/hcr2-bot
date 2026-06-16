from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchScoreListRow:
    id: int
    match_id: int
    match_start: str
    opponent: str
    season_name: str
    season_division: str
    player_name: str
    player_id: int
    score: int
    points: int
    absent: int
    checkin: int


@dataclass(frozen=True)
class MatchScoreDetail:
    id: int
    match_id: int
    match_start: str
    opponent: str
    season_name: str
    season_division: str
    player_name: str
    score: int
    points: int
    absent: int
    checkin: int


@dataclass(frozen=True)
class MatchScoreUnique:
    id: int
    score: int
    points: int
    absent: int
    checkin: int


@dataclass(frozen=True)
class MatchScoreEditBase:
    match_id: int
    player_id: int
    absent: int
    checkin: int


@dataclass(frozen=True)
class PlayerLookup:
    id: int
    name: str
    alias: str | None
