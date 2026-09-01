"""All SQL the broom ranking needs.

The window is defined by matches, not by dates: a fixed number of the most recent
matches keeps the sample size stable no matter how many events a season had.
"""
from __future__ import annotations

from hcr2.models.broom import BroomWindowRow, RosterMember
from hcr2.repositories.distances import AVERAGE_WINDOW as DISTANCE_AVERAGE_WINDOW
from hcr2.db.connection import connect_db, connect_dict_db


def window_match_ids(limit: int) -> list[int]:
    """The ``limit`` most recent match ids, newest first."""
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT id FROM match ORDER BY start DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row[0] for row in rows]


def fetch_roster() -> list[RosterMember]:
    with connect_dict_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, garage_power, is_leader
            FROM players
            WHERE active = 1 AND UPPER(team) = 'PLTE'
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
    return [
        RosterMember(
            player_id=row["id"],
            name=row["name"],
            garage_power=int(row["garage_power"] or 0),
            is_leader=bool(row["is_leader"]),
        )
        for row in rows
    ]


def fetch_window_rows(match_ids: list[int], player_ids: list[int]) -> list[BroomWindowRow]:
    if not match_ids or not player_ids:
        return []

    matches = ",".join("?" * len(match_ids))
    players = ",".join("?" * len(player_ids))
    with connect_dict_db() as conn:
        rows = conn.execute(
            f"""
            SELECT ms.match_id, ms.player_id, m.start, ms.score, ms.points,
                   ms.absent, ms.checkin, te.tracks
            FROM matchscore ms
            JOIN match m      ON m.id = ms.match_id
            JOIN teamevent te ON te.id = m.teamevent_id
            WHERE ms.match_id IN ({matches})
              AND ms.player_id IN ({players})
            """,
            (*match_ids, *player_ids),
        ).fetchall()

    return [
        BroomWindowRow(
            match_id=row["match_id"],
            player_id=row["player_id"],
            start=row["start"],
            score=int(row["score"] or 0),
            points=int(row["points"] or 0),
            absent=row["absent"],
            checkin=row["checkin"],
            tracks=row["tracks"],
        )
        for row in rows
    ]


def fetch_driven_totals(player_ids: list[int]) -> dict[int, int]:
    """Matches actually driven, over the whole history - what loyalty is measured on."""
    if not player_ids:
        return {}

    players = ",".join("?" * len(player_ids))
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT player_id, COUNT(*)
            FROM matchscore
            WHERE score > 0 AND player_id IN ({players})
            GROUP BY player_id
            """,
            tuple(player_ids),
        ).fetchall()
    return {row[0]: int(row[1]) for row in rows}


def fetch_km_averages(player_ids: list[int]) -> dict[int, tuple[float, int]]:
    """Average kilometres per week and the number of weeks stored, over the same
    window the profile uses - two definitions of "average" is how a number stops
    meaning anything."""
    if not player_ids:
        return {}

    players = ",".join("?" * len(player_ids))
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT player_id, AVG(km), COUNT(*) FROM (
                SELECT d.player_id, d.km,
                       ROW_NUMBER() OVER (
                           PARTITION BY d.player_id ORDER BY d.year DESC, d.week DESC
                       ) AS rn
                FROM distance d
                WHERE d.player_id IN ({players})
            )
            WHERE rn <= ?
            GROUP BY player_id
            """,
            (*player_ids, DISTANCE_AVERAGE_WINDOW),
        ).fetchall()
    return {row[0]: (float(row[1] or 0.0), int(row[2] or 0)) for row in rows}


def count_blockers_before(match_ids: list[int], player_ids: list[int]) -> dict[int, int]:
    """Check-in-no-shows *outside* the window. Reported as history, never ranked -
    a year-old incident is no argument for a kick today."""
    if not player_ids:
        return {}

    players = ",".join("?" * len(player_ids))
    exclude = ",".join("?" * len(match_ids)) if match_ids else "NULL"
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT player_id, COUNT(*)
            FROM matchscore
            WHERE checkin = 1
              AND (score IS NULL OR score = 0)
              AND player_id IN ({players})
              AND match_id NOT IN ({exclude})
            GROUP BY player_id
            """,
            (*player_ids, *match_ids),
        ).fetchall()
    return {row[0]: int(row[1]) for row in rows}
