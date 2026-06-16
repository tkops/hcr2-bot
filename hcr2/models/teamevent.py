from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamEvent:
    id: int
    name: str
    iso_year: int
    iso_week: int
    tracks: int
    max_score_per_track: int


@dataclass(frozen=True)
class TeamEventVehicle:
    id: int
    name: str

