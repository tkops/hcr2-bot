"""Weekly kilometres from the team distance chest.

One row per player and ISO week. The chest resets every period, so what the video
shows is already the week's distance - there is nothing to subtract, unlike the
cumulative donation totals.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from hcr2.models.distance import DistanceHistoryRow, DistanceRankRow, DistanceWeek
from hcr2.repositories import distances as distance_repo
from hcr2.repositories import players as player_repo
from hcr2.services import matchscores as matchscore_service


MAX_KM = 20000


def chest_path(year: int, week: int, path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    from hcr2.services.videos import chest_local_dir

    return chest_local_dir(year, week) / "chest.json"


def load_chest_file(path: str | Path) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"chest file not found: {path}"]
    except json.JSONDecodeError as e:
        return None, [f"chest file is not valid JSON: {e}"]
    except OSError as e:
        return None, [f"chest file unreadable: {type(e).__name__}: {e}"]

    if not isinstance(payload, dict) or not isinstance(payload.get("players"), list):
        return None, ["chest file must be one object with a players list"]
    return payload, []


@dataclass(frozen=True)
class AddDistanceResult:
    status: str
    player_id: int | None = None
    name: str = ""


@dataclass(frozen=True)
class ImportResult:
    status: str
    year: int = 0
    week: int = 0
    imported: int = 0
    total: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def current_year_week() -> tuple[int, int]:
    """Only the fallback for an empty table - callers that know the week pass it in.

    Which week a recording belongs to is not derivable from the recording date: the
    file name carries it (`w34.mp4`), so the reader passes --year/--week explicitly.
    """
    iso = date.today().isocalendar()
    return iso[0], iso[1]


def resolve_week(year: int | None, week: int | None) -> tuple[int, int] | None:
    if year is not None and week is not None:
        return (year, week) if 1 <= week <= 53 else None
    if year is None and week is None:
        return distance_repo.latest_week() or current_year_week()
    return None


def add_distance(*, player_input: str, year: int, week: int, km: int) -> AddDistanceResult:
    if not 0 <= km <= MAX_KM:
        return AddDistanceResult("INVALID_RANGE")
    if not 1 <= week <= 53:
        return AddDistanceResult("INVALID_WEEK")

    resolution = matchscore_service.resolve_player_id(player_input)
    if resolution.player_id is None:
        return AddDistanceResult("PLAYER_AMBIGUOUS" if resolution.matches else "PLAYER_NOT_FOUND")

    brief = player_repo.get_player_brief(resolution.player_id)
    if brief is None:
        return AddDistanceResult("PLAYER_NOT_FOUND", player_id=resolution.player_id)

    distance_repo.upsert(brief.id, year=year, week=week, km=km)
    return AddDistanceResult("ADDED", player_id=brief.id, name=brief.name)


def delete_distance(entry_id: int) -> bool:
    return distance_repo.delete_entry(entry_id) > 0


def ranking(year: int, week: int) -> list[DistanceRankRow]:
    return distance_repo.ranking(year, week)


def history(player_id: int, *, limit: int = 12) -> list[DistanceHistoryRow]:
    return distance_repo.history(player_id, limit=limit)


def weeks(limit: int = 12) -> list[DistanceWeek]:
    return distance_repo.weeks(limit)


def import_week(
    *,
    year: int,
    week: int,
    entries: list[dict],
    team_total: int | None = None,
    member_count: int | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> ImportResult:
    """Applies one week in full.

    The completeness proof is the **member count** from the screen header, not the
    chest total: the chest keeps counting kilometres from players who have left the
    team since, while the list only shows current members. Measured against a real
    recording the two were 207 km apart with every row read correctly, so a mismatch
    there is reported and never blocks.
    """
    errors: list[str] = []
    warnings: list[str] = []
    resolved: list[tuple[int, str, int]] = []
    seen: set[int] = set()

    if not 1 <= week <= 53:
        return ImportResult(status="ERRORS", year=year, week=week, errors=[f"week {week} is not a week number"])

    for entry in entries:
        player_id = entry.get("pid")
        km = entry.get("km")
        if not isinstance(player_id, int) or not isinstance(km, int):
            errors.append(f"{entry.get('name') or '?'}: pid and km must be whole numbers")
            continue
        brief = player_repo.get_player_brief(player_id)
        if brief is None:
            errors.append(f"player {player_id} does not exist")
            continue
        if player_id in seen:
            errors.append(f"player {player_id} ({brief.name}) appears more than once")
            continue
        if not 0 <= km <= MAX_KM:
            errors.append(f"{brief.name} ({player_id}): {km} km outside 0..{MAX_KM}")
            continue
        seen.add(player_id)
        resolved.append((player_id, brief.name, km))

    if member_count is not None and member_count != len(entries):
        message = (
            f"the screen shows {member_count} members, but {len(entries)} rows were read "
            "- a row was missed"
        )
        (warnings if force else errors).append(message + (" [forced]" if force else ""))

    total = sum(km for _, _, km in resolved)
    if team_total is not None and team_total != total:
        difference = team_total - total
        warnings.append(
            f"chest shows {team_total} km, the rows add up to {total} ({difference:+d}) "
            "- expected when someone left the team mid-period, suspicious if it is large"
        )

    if errors:
        return ImportResult(status="ERRORS", year=year, week=week, errors=errors, warnings=warnings, total=total)

    if dry_run:
        return ImportResult(
            status="DRY_RUN", year=year, week=week, imported=len(resolved), total=total, warnings=warnings
        )

    for player_id, _, km in resolved:
        distance_repo.upsert(player_id, year=year, week=week, km=km)

    return ImportResult(
        status="IMPORTED",
        year=year,
        week=week,
        imported=len(resolved),
        total=total,
        warnings=warnings,
    )
