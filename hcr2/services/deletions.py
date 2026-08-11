"""Guarded deletes.

The schema blocks deletes that would orphan result data (ON DELETE RESTRICT),
but a bare IntegrityError is useless to whoever typed the command. These
functions check the dependencies first and report what is in the way, so the
DB constraint stays the safety net rather than the user interface.

Dependent rows must be moved (e.g. `matchscore edit <id> --player <other-id>`)
or deleted before the parent row can go.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hcr2.repositories import integrity as integrity_repo
from hcr2.repositories import matches as match_repo
from hcr2.repositories import players as player_repo
from hcr2.repositories import seasons as season_repo
from hcr2.repositories import teamevents as teamevent_repo


# kind -> ((table, column, singular, plural), ...)
DEPENDENCIES: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "player": (
        ("matchscore", "player_id", "match score", "match scores"),
        ("donation", "player_id", "donation", "donations"),
    ),
    "match": (
        ("matchscore", "match_id", "match score", "match scores"),
    ),
    "season": (
        ("match", "season_number", "match", "matches"),
    ),
    "teamevent": (
        ("match", "teamevent_id", "match", "matches"),
    ),
}


@dataclass(frozen=True)
class DeleteOutcome:
    status: str  # "DELETED" | "BLOCKED"
    kind: str = ""
    key: int = 0
    blocks: list[tuple[str, int]] = field(default_factory=list)


def blocking_dependents(kind: str, key: int) -> list[tuple[str, int]]:
    blocks: list[tuple[str, int]] = []
    for table, column, singular, plural in DEPENDENCIES.get(kind, ()):
        count = integrity_repo.count_referencing_rows(table, column, key)
        if count:
            blocks.append((singular if count == 1 else plural, count))
    return blocks


def _guarded_delete(kind: str, key: int, deleter) -> DeleteOutcome:
    blocks = blocking_dependents(kind, key)
    if blocks:
        return DeleteOutcome(status="BLOCKED", kind=kind, key=key, blocks=blocks)
    deleter(key)
    return DeleteOutcome(status="DELETED", kind=kind, key=key)


def delete_player(player_id: int) -> DeleteOutcome:
    return _guarded_delete("player", player_id, player_repo.delete_player)


def delete_match(match_id: int) -> DeleteOutcome:
    return _guarded_delete("match", match_id, match_repo.delete_match)


def delete_season(number: int) -> DeleteOutcome:
    return _guarded_delete("season", number, season_repo.delete_season)


def delete_teamevent(teamevent_id: int) -> DeleteOutcome:
    return _guarded_delete("teamevent", teamevent_id, teamevent_repo.delete_teamevent)
