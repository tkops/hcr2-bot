from __future__ import annotations

from hcr2.db.connection import connect_db, connect_dict_db
from hcr2.models.distance import (
    DistanceEntry,
    DistanceHistoryRow,
    DistanceRankRow,
    DistanceWeek,
    PlayerDistanceSummary,
)


# How many weeks back the average in the profile looks. Far enough to survive one
# missed week, short enough to still describe the current form.
AVERAGE_WINDOW = 8


def upsert(player_id: int, *, year: int, week: int, km: int) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO distance (player_id, year, week, km)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(player_id, year, week) DO UPDATE SET km = excluded.km
            """,
            (player_id, year, week, km),
        )


def delete_entry(entry_id: int) -> int:
    with connect_db() as conn:
        return conn.execute("DELETE FROM distance WHERE id = ?", (entry_id,)).rowcount


def get_entry(entry_id: int) -> DistanceEntry | None:
    with connect_dict_db() as conn:
        row = conn.execute(
            "SELECT id, player_id, year, week, km FROM distance WHERE id = ?", (entry_id,)
        ).fetchone()
    return _entry(row) if row else None


def latest_week() -> tuple[int, int] | None:
    with connect_db() as conn:
        row = conn.execute("SELECT year, week FROM distance ORDER BY year DESC, week DESC LIMIT 1").fetchone()
    return (row[0], row[1]) if row else None


def ranking(year: int, week: int) -> list[DistanceRankRow]:
    with connect_dict_db() as conn:
        rows = conn.execute(
            """
            SELECT d.player_id, p.name, d.km,
                   (SELECT AVG(h.km) FROM distance h
                     WHERE h.player_id = d.player_id
                       AND (h.year * 100 + h.week) <= (d.year * 100 + d.week)
                       AND (h.year * 100 + h.week) > (d.year * 100 + d.week) - ?) AS average,
                   (SELECT COUNT(*) FROM distance h WHERE h.player_id = d.player_id) AS weeks
            FROM distance d
            JOIN players p ON p.id = d.player_id
            WHERE d.year = ? AND d.week = ?
            ORDER BY d.km DESC, p.name COLLATE NOCASE
            """,
            (AVERAGE_WINDOW, year, week),
        ).fetchall()

    return [
        DistanceRankRow(
            player_id=row["player_id"],
            name=row["name"],
            km=row["km"],
            average=float(row["average"] or 0),
            weeks=int(row["weeks"] or 0),
        )
        for row in rows
    ]


def history(player_id: int, *, limit: int = 12) -> list[DistanceHistoryRow]:
    with connect_dict_db() as conn:
        rows = conn.execute(
            """
            SELECT d.year, d.week, d.km,
                   (SELECT COUNT(*) + 1 FROM distance o
                     WHERE o.year = d.year AND o.week = d.week AND o.km > d.km) AS rank,
                   (SELECT COUNT(*) FROM distance o
                     WHERE o.year = d.year AND o.week = d.week) AS of
            FROM distance d
            WHERE d.player_id = ?
            ORDER BY d.year DESC, d.week DESC
            LIMIT ?
            """,
            (player_id, limit),
        ).fetchall()

    return [
        DistanceHistoryRow(
            year=row["year"], week=row["week"], km=row["km"], rank=row["rank"], of=row["of"]
        )
        for row in rows
    ]


def weeks(limit: int = 12) -> list[DistanceWeek]:
    with connect_dict_db() as conn:
        rows = conn.execute(
            """
            SELECT year, week, SUM(km) AS total, COUNT(*) AS players
            FROM distance
            GROUP BY year, week
            ORDER BY year DESC, week DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        DistanceWeek(year=row["year"], week=row["week"], total=int(row["total"] or 0), players=row["players"])
        for row in rows
    ]


def summary_for_player(player_id: int) -> PlayerDistanceSummary:
    with connect_dict_db() as conn:
        row = conn.execute(
            """
            SELECT AVG(km) AS average, COUNT(*) AS weeks
            FROM (SELECT km FROM distance WHERE player_id = ?
                  ORDER BY year DESC, week DESC LIMIT ?)
            """,
            (player_id, AVERAGE_WINDOW),
        ).fetchone()
        last = conn.execute(
            "SELECT km, year, week FROM distance WHERE player_id = ? ORDER BY year DESC, week DESC LIMIT 1",
            (player_id,),
        ).fetchone()

    return PlayerDistanceSummary(
        average=float(row["average"] or 0),
        weeks=int(row["weeks"] or 0),
        last_km=last["km"] if last else None,
        last_year=last["year"] if last else None,
        last_week=last["week"] if last else None,
    )


def _entry(row) -> DistanceEntry:
    return DistanceEntry(
        id=row["id"], player_id=row["player_id"], year=row["year"], week=row["week"], km=row["km"]
    )
