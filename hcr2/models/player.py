from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlayerListRow:
    id: int
    name: str
    alias: str | None
    garage_power: int
    active: int
    created_at: str | None
    birthday: str | None
    team: str | None
    discord_name: str
    is_leader: int
    active_modified: str | None
    away_until: str | None


@dataclass(frozen=True)
class PlayerDetail:
    id: int
    name: str
    alias: str | None
    garage_power: int
    active: int
    birthday: str | None
    team: str | None
    discord_name: str | None
    created_at: str | None
    last_modified: str | None
    active_modified: str | None
    away_from: str | None
    away_until: str | None
    is_leader: int
    about: str | None
    preferred_vehicles: str | None
    playstyle: str | None
    language: str | None
    emoji: str | None
    match_count: int
    first_match: str | None
    last_match: str | None
    avg_km: float = 0.0
    km_weeks: int = 0


@dataclass(frozen=True)
class PlayerBirthdayRow:
    id: int
    name: str
    birthday: str
    emoji: str
    active: int


@dataclass(frozen=True)
class PlayerSearchRow:
    id: int
    name: str
    alias: str | None
    garage_power: int
    active: int
    discord_name: str


@dataclass(frozen=True)
class PlayerLeaderRow:
    id: int
    name: str
    discord_name: str


@dataclass(frozen=True)
class PlayerAbsentRow:
    id: int
    name: str
    team: str
    away_until: str


@dataclass(frozen=True)
class PlayerBrief:
    id: int
    name: str
    alias: str | None
    discord_name: str | None
