from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Vehicle:
    id: int
    name: str
    shortname: str

