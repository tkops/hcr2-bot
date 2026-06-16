from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Season:
    number: int
    name: str
    start: str
    division: str

