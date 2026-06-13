from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DonationEntry:
    id: int | None
    date: str
    total: int


@dataclass(frozen=True)
class DonationStats:
    entries: list[tuple[int | None, str, int, int]]
    last_total: int
    total_donated: int
    avg_monthly_increment: float


@dataclass(frozen=True)
class DonationDateSummary:
    date: str
    count: int


@dataclass(frozen=True)
class DonationDateEntry:
    id: int
    player_id: int
    player_name: str | None
    team: str
    total: int


@dataclass(frozen=True)
class DonationIndexRow:
    player_id: int
    player_name: str
    matches: int
    total: int
    index: float
