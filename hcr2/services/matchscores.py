from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hcr2.models.matchscore import MatchScoreDetail, MatchScoreListRow, PlayerLookup
from hcr2.repositories import matchscores as matchscore_repo
from modules.common import is_absent_on, parse_int, parse_ymd


AddStatus = Literal["CHANGED", "UNCHANGED", "INVALID_RANGE", "PLAYER_NOT_FOUND", "PLAYER_AMBIGUOUS"]
EditStatus = Literal[
    "UPDATED",
    "NOTHING_TO_UPDATE",
    "NOT_FOUND",
    "PLAYER_NOT_FOUND",
    "PLAYER_CLASH",
    "SCORE_OUT_OF_RANGE",
    "POINTS_OUT_OF_RANGE",
]


@dataclass(frozen=True)
class PlayerResolution:
    player_id: int | None
    matches: list[PlayerLookup]

    @property
    def is_ambiguous(self) -> bool:
        return len(self.matches) > 1

    @property
    def is_missing(self) -> bool:
        return self.player_id is None and not self.matches


@dataclass(frozen=True)
class AddScoreResult:
    status: AddStatus
    player_resolution: PlayerResolution | None = None


@dataclass(frozen=True)
class ListScoresResult:
    rows: list[MatchScoreListRow]


@dataclass(frozen=True)
class DeleteScoreResult:
    row: MatchScoreDetail | None


@dataclass(frozen=True)
class EditScoreResult:
    status: EditStatus
    row: MatchScoreDetail | None = None
    player_id: int | None = None
    clash_id: int | None = None
    match_id: int | None = None


def resolve_player_id(player_input: str) -> PlayerResolution:
    player_id = parse_int(player_input, default=None)
    if player_id is not None:
        return PlayerResolution(player_id=player_id, matches=[])

    matches = matchscore_repo.find_players(player_input)
    if len(matches) == 1:
        return PlayerResolution(player_id=matches[0].id, matches=matches)
    return PlayerResolution(player_id=None, matches=matches)


def add_score(
    *,
    match_id: int,
    player_input: str,
    score: int,
    points: int,
    absent_override: int | None = None,
    checkin_override: int | None = None,
) -> AddScoreResult:
    if not (0 <= score <= 75000 and 0 <= points <= 300):
        return AddScoreResult("INVALID_RANGE")

    player_resolution = resolve_player_id(player_input)
    if player_resolution.is_missing:
        return AddScoreResult("PLAYER_NOT_FOUND", player_resolution)
    if player_resolution.is_ambiguous:
        return AddScoreResult("PLAYER_AMBIGUOUS", player_resolution)

    player_id = player_resolution.player_id
    if player_id is None:
        return AddScoreResult("PLAYER_NOT_FOUND", player_resolution)

    absent = absent_override if absent_override is not None else compute_absent(match_id, player_id)
    checkin = checkin_override if checkin_override is not None else 0

    existing = matchscore_repo.fetch_by_match_player(match_id, player_id)
    if existing:
        changed = (
            existing.score != score
            or existing.points != points
            or (existing.absent or 0) != absent
            or (existing.checkin or 0) != checkin
        )
        matchscore_repo.update_score(existing.id, score=score, points=points, absent=absent, checkin=checkin)
        return AddScoreResult("CHANGED" if changed else "UNCHANGED", player_resolution)

    matchscore_repo.insert_score(
        match_id=match_id,
        player_id=player_id,
        score=score,
        points=points,
        absent=absent,
        checkin=checkin,
    )
    return AddScoreResult("CHANGED", player_resolution)


def delete_score(score_id: int) -> DeleteScoreResult:
    row = matchscore_repo.fetch_score_by_id(score_id)
    if row is None:
        return DeleteScoreResult(row=None)
    matchscore_repo.delete_score(score_id)
    return DeleteScoreResult(row=row)


def list_scores(
    *,
    show_all: bool,
    season_filter: str | None,
    match_filter: int | None,
) -> ListScoresResult:
    rows = matchscore_repo.query_rows(
        season_filter,
        match_filter,
        force_current_when_all=show_all,
    )
    if rows and not show_all and not match_filter:
        last_match_id = rows[0].match_id
        rows = [row for row in rows if row.match_id == last_match_id]
    return ListScoresResult(rows=rows)


def edit_score(
    score_id: int,
    *,
    score: int | None = None,
    points: int | None = None,
    absent: int | None = None,
    checkin: int | None = None,
    player_id: int | None = None,
    toggle_absent: bool = False,
    toggle_checkin: bool = False,
) -> EditScoreResult:
    if (
        score is None
        and points is None
        and absent is None
        and checkin is None
        and player_id is None
        and not (toggle_absent or toggle_checkin)
    ):
        return EditScoreResult("NOTHING_TO_UPDATE")

    base = matchscore_repo.get_edit_base(score_id)
    if not base:
        return EditScoreResult("NOT_FOUND")

    match_id = base.match_id
    current_player_id = base.player_id

    if toggle_absent:
        absent = 0 if (base.absent or 0) else 1
    if toggle_checkin:
        checkin = 0 if (base.checkin or 0) else 1

    if player_id is not None and player_id != current_player_id:
        if not matchscore_repo.player_exists(player_id):
            return EditScoreResult("PLAYER_NOT_FOUND", player_id=player_id)
        clash_id = matchscore_repo.find_score_id(match_id, player_id)
        if clash_id and clash_id != score_id:
            return EditScoreResult("PLAYER_CLASH", player_id=player_id, clash_id=clash_id, match_id=match_id)

    updates: dict[str, object] = {}
    if score is not None:
        if not (0 <= score <= 75000):
            return EditScoreResult("SCORE_OUT_OF_RANGE")
        updates["score"] = score
    if points is not None:
        if not (0 <= points <= 300):
            return EditScoreResult("POINTS_OUT_OF_RANGE")
        updates["points"] = points
    if absent is not None:
        updates["absent"] = absent
    if checkin is not None:
        updates["checkin"] = checkin
    if player_id is not None and player_id != current_player_id:
        updates["player_id"] = player_id

    if (score is not None or points is not None) and absent is None:
        updates["absent"] = compute_absent(match_id, player_id if player_id is not None else current_player_id)

    if not updates:
        return EditScoreResult("NOTHING_TO_UPDATE")

    matchscore_repo.update_score_fields(score_id, updates)
    return EditScoreResult("UPDATED", row=matchscore_repo.fetch_score_by_id(score_id))


def compute_absent(match_id: int, player_id: int) -> int:
    match_start = matchscore_repo.get_match_start(match_id)
    if not match_start:
        return 0
    match_day = parse_ymd(match_start)
    away_window = matchscore_repo.get_player_away_window(player_id)
    if not away_window:
        return 0
    return 1 if is_absent_on(match_day, away_window[0], away_window[1]) else 0
