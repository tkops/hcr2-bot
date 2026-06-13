from __future__ import annotations

from hcr2.db.connection import connect_db
from hcr2.models.season import Season


def get_next_season_number() -> int:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM season")
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 1


def season_exists(number: int) -> bool:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM season WHERE number = ?", (number,))
        return cur.fetchone() is not None


def add_season(number: int, name: str, start: str, division: str) -> None:
    with connect_db() as conn:
        conn.execute(
            "INSERT INTO season (number, name, start, division) VALUES (?, ?, ?, ?)",
            (number, name, start, division),
        )


def update_division(number: int, division: str) -> None:
    with connect_db() as conn:
        conn.execute("UPDATE season SET division = ? WHERE number = ?", (division, number))


def delete_season(number: int) -> None:
    with connect_db() as conn:
        conn.execute("DELETE FROM season WHERE number = ?", (number,))


def list_latest(limit: int = 10) -> list[Season]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT number, name, start, division FROM season ORDER BY number DESC LIMIT ?",
            (limit,),
        )
        return [_row_to_season(row) for row in cur.fetchall()]


def list_all() -> list[Season]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT number, name, start, division FROM season ORDER BY number")
        return [_row_to_season(row) for row in cur.fetchall()]


def list_by_number(number: int) -> list[Season]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT number, name, start, division FROM season WHERE number = ?", (number,))
        return [_row_to_season(row) for row in cur.fetchall()]


def list_by_division(division: str) -> list[Season]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT number, name, start, division FROM season WHERE division = ? ORDER BY number",
            (division,),
        )
        return [_row_to_season(row) for row in cur.fetchall()]


def _row_to_season(row) -> Season:
    return Season(number=row[0], name=row[1], start=row[2], division=row[3])
