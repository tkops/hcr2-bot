from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any

from hcr2.models.player import (
    PlayerAbsentRow,
    PlayerBirthdayRow,
    PlayerBrief,
    PlayerDetail,
    PlayerLeaderRow,
    PlayerListRow,
    PlayerSearchRow,
)
from hcr2.repositories import players as player_repo
from hcr2.services import deletions as deletions_service


TEAM_RE = re.compile(r"^(PLTE|PL[1-9])$")
ALIAS_BASE_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class PlayerListResult:
    rows: list[PlayerListRow]
    active_count: int


@dataclass(frozen=True)
class PlayerBirthdayListResult:
    rows: list[tuple[int, PlayerBirthdayRow]]
    active_only: bool


@dataclass(frozen=True)
class PlayerAbsentListResult:
    rows: list[tuple[int, PlayerAbsentRow]]


@dataclass(frozen=True)
class PlayerResolutionResult:
    status: str
    player_id: int | None = None
    matches: list[PlayerSearchRow] | None = None


@dataclass(frozen=True)
class ExplicitPlayerResolutionResult:
    status: str
    player_id: int | None = None


@dataclass(frozen=True)
class AwaySetResult:
    status: str
    player_id: int | None = None
    brief: PlayerBrief | None = None
    away_from: str | None = None
    away_until: str | None = None


@dataclass(frozen=True)
class AwayClearResult:
    status: str
    player_id: int | None = None
    brief: PlayerBrief | None = None


@dataclass(frozen=True)
class AddPlayerResult:
    status: str
    player_id: int | None = None
    alias: str | None = None
    alias_generated: bool = False
    team: str | None = None
    alias_base: str | None = None


@dataclass(frozen=True)
class EditPlayerResult:
    status: str
    alias: str | None = None
    conflict_alias: str | None = None
    conflict_player_id: int | None = None


def list_players(*, active_only: bool = False, sort_by: str = "gp", team_filter: str | None = None) -> PlayerListResult:
    return PlayerListResult(
        rows=player_repo.list_players(active_only=active_only, sort_by=sort_by, team_filter=team_filter),
        active_count=player_repo.count_active_players(),
    )


def get_player_detail(player_id: int) -> PlayerDetail | None:
    return player_repo.get_player_detail(player_id)


def birthday_ids_for_today() -> list[int]:
    return player_repo.get_birthday_player_ids(today_mm_dd())


def list_birthdays(*, active_only: bool = False, num: int | None = None) -> PlayerBirthdayListResult:
    items: list[tuple[int, PlayerBirthdayRow]] = []
    for row in player_repo.list_birthday_players(active_only=active_only):
        days_until = days_until_mmdd(row.birthday)
        if days_until is None:
            continue
        items.append((days_until, row))

    items.sort(key=lambda item: item[0])
    if num is not None and num >= 0:
        items = items[:num]
    return PlayerBirthdayListResult(rows=items, active_only=active_only)


def search_players(term: str) -> list[PlayerSearchRow]:
    return player_repo.search_players_like(term)


def resolve_player_id_exact(term: str) -> int | None:
    rows = player_repo.resolve_player_id_exact(term)
    if len(rows) == 1:
        return rows[0]
    return None


def resolve_player_id_fuzzy(term: str) -> PlayerResolutionResult:
    player_id = resolve_player_id_exact(term)
    if player_id is not None:
        return PlayerResolutionResult("FOUND", player_id=player_id)

    matches = search_players(term)
    if len(matches) == 0:
        return PlayerResolutionResult("NOT_FOUND", matches=matches)
    if len(matches) == 1:
        return PlayerResolutionResult("FOUND", player_id=matches[0].id, matches=matches)
    return PlayerResolutionResult("AMBIGUOUS", matches=matches)


def resolve_player_id_explicit(
    *,
    player_id: str | None = None,
    player_name: str | None = None,
    discord_name: str | None = None,
) -> ExplicitPlayerResolutionResult:
    if player_id:
        try:
            return ExplicitPlayerResolutionResult("FOUND", player_id=int(player_id))
        except ValueError:
            return ExplicitPlayerResolutionResult("INVALID_ID")

    if discord_name:
        rows = player_repo.find_player_ids_by_discord(discord_name)
        if not rows:
            return ExplicitPlayerResolutionResult("DISCORD_NOT_FOUND")
        if len(rows) > 1:
            return ExplicitPlayerResolutionResult("DISCORD_AMBIGUOUS")
        return ExplicitPlayerResolutionResult("FOUND", player_id=rows[0])

    if player_name:
        rows = player_repo.find_player_ids_by_name(player_name)
        if not rows:
            fuzzy = resolve_player_id_fuzzy(player_name)
            return ExplicitPlayerResolutionResult(fuzzy.status, player_id=fuzzy.player_id)
        if len(rows) > 1:
            return ExplicitPlayerResolutionResult("NAME_AMBIGUOUS")
        return ExplicitPlayerResolutionResult("FOUND", player_id=rows[0])

    return ExplicitPlayerResolutionResult("MISSING_SELECTOR")


def set_away_for_player(player_id: int, *, days: int) -> AwaySetResult:
    now = datetime.now()
    away_from = now.strftime("%Y-%m-%d %H:%M:%S")
    away_until = (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    player_repo.set_away(player_id, away_from, away_until)
    return AwaySetResult(
        status="SET",
        player_id=player_id,
        brief=player_repo.get_player_brief(player_id),
        away_from=away_from,
        away_until=away_until,
    )


def clear_away_for_player(player_id: int) -> AwayClearResult:
    player_repo.clear_away(player_id)
    return AwayClearResult(status="CLEARED", player_id=player_id, brief=player_repo.get_player_brief(player_id))


def parse_weeks_token(token: str | None) -> int:
    if not token:
        return 7
    match = re.fullmatch(r"\s*([1-4])\s*w?\s*", token, flags=re.IGNORECASE)
    if not match:
        raise ValueError("Use 1w, 2w, 3w or 4w.")
    return int(match.group(1)) * 7


def list_leaders() -> list[PlayerLeaderRow]:
    return player_repo.list_leaders()


def list_absent() -> PlayerAbsentListResult:
    items: list[tuple[int, PlayerAbsentRow]] = []
    today = date.today()
    for row in player_repo.list_absent_players():
        try:
            until_dt = datetime.strptime(row.away_until[:19], "%Y-%m-%d %H:%M:%S")
            days = max(0, (until_dt.date() - today).days)
        except (TypeError, ValueError):
            days = 0
        items.append((days, row))
    items.sort(key=lambda item: item[0], reverse=True)
    return PlayerAbsentListResult(rows=items)


def activate_player(player_id: int) -> None:
    player_repo.set_active(player_id, True)


def deactivate_player(player_id: int) -> None:
    player_repo.set_active(player_id, False)


def delete_player(player_id: int):
    """Blocked while match scores or donations still reference the player."""
    return deletions_service.delete_player(player_id)


def edit_player(
    player_id: int,
    *,
    name: str | None = None,
    alias: str | None = None,
    gp: int | None = None,
    active: bool | None = None,
    birthday: str | None = None,
    team: str | None = None,
    discord_name: str | None = None,
    leader: bool | None = None,
    about: str | None = None,
    vehicles: str | None = None,
    playstyle: str | None = None,
    language: str | None = None,
    emoji: str | None = None,
) -> EditPlayerResult:
    current = player_repo.get_player_team_alias(player_id)
    if not current:
        return EditPlayerResult("NOT_FOUND")

    current_team, current_alias = current
    target_team = team or current_team
    target_alias = alias if alias is not None else current_alias

    if target_team == "PLTE":
        if not target_alias:
            return EditPlayerResult("ALIAS_REQUIRED")
        for other_id, other_alias in player_repo.list_plte_aliases_except(player_id):
            if other_alias and (target_alias in other_alias or other_alias in target_alias):
                return EditPlayerResult(
                    "ALIAS_CONFLICT",
                    alias=target_alias,
                    conflict_alias=other_alias,
                    conflict_player_id=other_id,
                )

    updates: dict[str, Any] = {}
    if name is not None:
        updates["name"] = name
    if alias is not None:
        updates["alias"] = alias
    if gp is not None:
        updates["garage_power"] = gp
    if active is not None:
        updates["active"] = 1 if active else 0
    if birthday is not None:
        updates["birthday"] = birthday
    if team is not None:
        updates["team"] = team
    if discord_name is not None:
        updates["discord_name"] = discord_name
    if leader is not None:
        updates["is_leader"] = 1 if leader else 0
    if about is not None:
        updates["about"] = about
    if vehicles is not None:
        updates["preferred_vehicles"] = vehicles
    if playstyle is not None:
        updates["playstyle"] = playstyle
    if language is not None:
        updates["language"] = language
    if emoji is not None:
        updates["emoji"] = emoji

    if not updates:
        return EditPlayerResult("NOTHING_TO_UPDATE")

    player_repo.update_player_fields(player_id, updates)
    return EditPlayerResult("UPDATED")


def add_player(
    *,
    name: str,
    alias: str | None = None,
    gp: int = 0,
    active: bool = True,
    birthday: str | None = None,
    team: str | None = None,
    discord_name: str | None = None,
) -> AddPlayerResult:
    team = (team or "").upper().strip()
    if not is_valid_team(team):
        return AddPlayerResult(status="INVALID_TEAM", team=team)

    alias = sanitize_alias_token(alias) if alias else None
    alias_generated = False
    alias_base = None

    if team == "PLTE":
        if not alias:
            alias_base = alias_base_from_name(name)
            alias_candidate = next_free_alias(alias_base, team_scope="PLTE")
            if not alias_candidate:
                return AddPlayerResult(status="ALIAS_GENERATION_FAILED", team=team, alias_base=alias_base)
            alias = alias_candidate
            alias_generated = True
        elif player_repo.alias_exists(alias, team_scope="PLTE"):
            return AddPlayerResult(status="ALIAS_CONFLICT", alias=alias, team=team)

    player_id = player_repo.add_player(
        name=name,
        alias=alias,
        garage_power=gp,
        active=active,
        birthday=birthday,
        team=team,
        discord_name=discord_name,
    )
    return AddPlayerResult(
        status="ADDED",
        player_id=player_id,
        alias=alias,
        alias_generated=alias_generated,
        team=team,
        alias_base=alias_base,
    )


def parse_birthday(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw.strip("."), "%d.%m")
        return dt.strftime("%m-%d")
    except ValueError:
        return None


def today_mm_dd() -> str:
    return datetime.now().strftime("%m-%d")


def days_until_mmdd(mmdd: str) -> int | None:
    try:
        month, day = map(int, mmdd.split("-"))
    except (AttributeError, TypeError, ValueError):
        return None

    today = date.today()
    target = safe_date(today.year, month, day)
    if target is None:
        return None
    if target < today:
        target = safe_date(today.year + 1, month, day)
        if target is None:
            return None
    return (target - today).days


def safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return date(year, 3, 1)
        return None


def is_valid_team(team: str | None) -> bool:
    return bool(team and TEAM_RE.fullmatch(team))


def alias_base_from_name(name: str) -> str:
    base = ALIAS_BASE_RE.sub("", (name or "").lower())
    return base or "player"


def sanitize_alias_token(alias: str | None) -> str:
    return ALIAS_BASE_RE.sub("", (alias or "").lower())


def next_free_alias(base: str, *, team_scope: str | None) -> str | None:
    for n in range(1, 10):
        candidate = f"{base}{n}"
        if not player_repo.alias_exists(candidate, team_scope=team_scope):
            return candidate
    return None
