from __future__ import annotations

import re

from hcr2.db.connection import connect_db
from hcr2.models.matchscore import (
    MatchScoreDetail,
    MatchScoreEditBase,
    MatchScoreListRow,
    MatchScoreUnique,
    PlayerLookup,
)


def get_match_start(match_id: int) -> str | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT start FROM match WHERE id = ?", (match_id,))
        row = cur.fetchone()
        return row[0] if row else None


def get_player_away_window(player_id: int) -> tuple[str | None, str | None] | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT away_from, away_until FROM players WHERE id = ?", (player_id,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else None


def fetch_score_by_id(score_id: int) -> MatchScoreDetail | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                ms.id, m.id, m.start, m.opponent,
                s.name, s.division, p.name,
                ms.score, ms.points, ms.absent, ms.checkin
            FROM matchscore ms
            JOIN match   m ON ms.match_id      = m.id
            JOIN season  s ON m.season_number  = s.number
            JOIN players p ON ms.player_id     = p.id
            WHERE ms.id = ?
            """,
            (score_id,),
        )
        row = cur.fetchone()
        return _detail_from_row(row) if row else None


def fetch_by_match_player(match_id: int, player_id: int) -> MatchScoreUnique | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, score, points, absent, checkin FROM matchscore WHERE match_id=? AND player_id=?",
            (match_id, player_id),
        )
        row = cur.fetchone()
        return _unique_from_row(row) if row else None


def query_rows(
    season_filter: str | None,
    match_filter: int | None,
    *,
    force_current_when_all: bool = False,
) -> list[MatchScoreListRow]:
    base = """
        SELECT ms.id, m.id, m.start, m.opponent,
               s.name, s.division, p.name, p.id, ms.score, ms.points, ms.absent, ms.checkin
        FROM matchscore ms
        JOIN match m ON ms.match_id = m.id
        JOIN season s ON m.season_number = s.number
        JOIN players p ON ms.player_id = p.id
    """
    where: list[str] = []
    values: list[object] = []
    if force_current_when_all and not season_filter and not match_filter:
        where.append("s.number = (SELECT MAX(number) FROM season)")
    if season_filter:
        clause, clause_values = _season_clause(season_filter)
        if clause:
            where.append(clause)
            values.extend(clause_values)
    if match_filter:
        where.append("m.id = ?")
        values.append(match_filter)
    query = base + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY m.id DESC, ms.score DESC"

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(query, values)
        return [_list_row_from_row(row) for row in cur.fetchall()]


def find_players(player_input: str) -> list[PlayerLookup]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, alias FROM players
            WHERE name LIKE ? OR alias LIKE ?
            """,
            (f"%{player_input}%", f"%{player_input}%"),
        )
        return [PlayerLookup(id=row[0], name=row[1], alias=row[2]) for row in cur.fetchall()]


def get_match_result(match_id: int) -> tuple[int, int]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT score_ladys, score_opponent FROM match WHERE id = ?", (match_id,))
        return cur.fetchone() or (0, 0)


def insert_score(
    *,
    match_id: int,
    player_id: int,
    score: int,
    points: int,
    absent: int,
    checkin: int,
) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (match_id, player_id, score, points, absent, checkin),
        )


def update_score(score_id: int, *, score: int, points: int, absent: int, checkin: int) -> int:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE matchscore
            SET score=?, points=?, absent=?, checkin=?
            WHERE id=?
            """,
            (score, points, absent, checkin, score_id),
        )
        return cur.rowcount


def delete_score(score_id: int) -> int:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM matchscore WHERE id = ?", (score_id,))
        return cur.rowcount


def get_edit_base(score_id: int) -> MatchScoreEditBase | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT match_id, player_id, absent, checkin FROM matchscore WHERE id = ?", (score_id,))
        row = cur.fetchone()
        return MatchScoreEditBase(row[0], row[1], row[2], row[3]) if row else None


def player_exists(player_id: int) -> bool:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM players WHERE id = ?", (player_id,))
        return cur.fetchone() is not None


def find_score_id(match_id: int, player_id: int) -> int | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM matchscore WHERE match_id=? AND player_id=?", (match_id, player_id))
        row = cur.fetchone()
        return row[0] if row else None


def update_score_fields(score_id: int, updates: dict[str, object]) -> int:
    if not updates:
        return 0

    fields = [f"{column}=?" for column in updates]
    values = list(updates.values()) + [score_id]
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE matchscore SET {', '.join(fields)} WHERE id = ?", values)
        return cur.rowcount


def _season_clause(season_filter: str) -> tuple[str, list[object]]:
    if season_filter == "__CURRENT__":
        return "s.number = (SELECT MAX(number) FROM season)", []
    match = re.fullmatch(r"\s*[sS]?\s*(\d+)\s*", str(season_filter))
    if match:
        return "s.number = ?", [int(match.group(1))]
    pattern = str(season_filter).replace("*", "%")
    return "s.name LIKE ?", [pattern]


def _list_row_from_row(row) -> MatchScoreListRow:
    return MatchScoreListRow(
        id=row[0],
        match_id=row[1],
        match_start=row[2],
        opponent=row[3],
        season_name=row[4],
        season_division=row[5],
        player_name=row[6],
        player_id=row[7],
        score=row[8],
        points=row[9],
        absent=row[10],
        checkin=row[11],
    )


def _detail_from_row(row) -> MatchScoreDetail:
    return MatchScoreDetail(
        id=row[0],
        match_id=row[1],
        match_start=row[2],
        opponent=row[3],
        season_name=row[4],
        season_division=row[5],
        player_name=row[6],
        score=row[7],
        points=row[8],
        absent=row[9],
        checkin=row[10],
    )


def _unique_from_row(row) -> MatchScoreUnique:
    return MatchScoreUnique(
        id=row[0],
        score=row[1],
        points=row[2],
        absent=row[3],
        checkin=row[4],
    )
