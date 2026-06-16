from __future__ import annotations

from hcr2.db.connection import connect_db
from hcr2.models.match import MatchDetail, MatchSummary


def teamevent_exists(teamevent_id: int) -> bool:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM teamevent WHERE id = ? LIMIT 1", (teamevent_id,))
        return cur.fetchone() is not None


def latest_teamevent_id() -> int | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM teamevent
            ORDER BY iso_year DESC, iso_week DESC, id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return row[0] if row else None


def latest_match_start_between(start_inclusive: str, end_exclusive: str) -> str | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT start
            FROM match
            WHERE start >= ? AND start < ?
            ORDER BY start DESC, id DESC
            LIMIT 1
            """,
            (start_inclusive, end_exclusive),
        )
        row = cur.fetchone()
        return row[0] if row else None


def add_match(
    *,
    teamevent_id: int,
    season_number: int,
    start: str,
    opponent: str,
    score_ladys: int,
    score_opponent: int,
) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO match (teamevent_id, season_number, start, opponent, score_ladys, score_opponent)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (teamevent_id, season_number, start, opponent, score_ladys, score_opponent),
        )


def update_match(match_id: int, updates: dict[str, object]) -> int:
    if not updates:
        return 0

    fields = [f"{column} = ?" for column in updates]
    values = list(updates.values()) + [match_id]
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE match SET {', '.join(fields)} WHERE id = ?", values)
        return cur.rowcount


def list_matches(*, season_number: int | None = None, all_seasons: bool = False) -> list[MatchSummary]:
    with connect_db() as conn:
        cur = conn.cursor()
        if all_seasons:
            cur.execute(
                """
                SELECT m.id, m.start, t.name, m.opponent
                FROM match m
                JOIN teamevent t ON m.teamevent_id = t.id
                ORDER BY m.start DESC
                """
            )
        else:
            cur.execute(
                """
                SELECT m.id, m.start, t.name, m.opponent
                FROM match m
                JOIN teamevent t ON m.teamevent_id = t.id
                WHERE m.season_number = ?
                ORDER BY m.start DESC
                """,
                (season_number,),
            )
        return [_summary_from_row(row) for row in cur.fetchall()]


def get_match(match_id: int) -> MatchDetail | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.id, m.start, m.season_number, m.opponent, t.name, m.score_ladys, m.score_opponent
            FROM match m
            JOIN teamevent t ON m.teamevent_id = t.id
            WHERE m.id = ?
            """,
            (match_id,),
        )
        row = cur.fetchone()
        return _detail_from_row(row) if row else None


def delete_match(match_id: int) -> None:
    with connect_db() as conn:
        conn.execute("DELETE FROM match WHERE id = ?", (match_id,))


def _summary_from_row(row) -> MatchSummary:
    return MatchSummary(id=row[0], start=row[1], event_name=row[2], opponent=row[3])


def _detail_from_row(row) -> MatchDetail:
    return MatchDetail(
        id=row[0],
        start=row[1],
        season_number=row[2],
        opponent=row[3],
        event_name=row[4],
        score_ladys=row[5],
        score_opponent=row[6],
    )

