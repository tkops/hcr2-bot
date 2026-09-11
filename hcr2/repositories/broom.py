"""All SQL the broom ranking needs.

The window is a season by default - that is the unit the decision is made in: at the
end of a season the leadership says goodbye to a handful of players, so the evidence
has to be exactly that season and nothing older. ``window_match_ids`` keeps the old
fixed-count window available for a look across season boundaries.
"""
from __future__ import annotations

from datetime import date, timedelta

from hcr2.models.broom import BroomWindowRow, RosterMember
from hcr2.db.connection import connect_db, connect_dict_db


def window_match_ids(limit: int) -> list[int]:
    """The ``limit`` most recent match ids, newest first."""
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT id FROM match ORDER BY start DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row[0] for row in rows]


def season_match_ids(season: int) -> list[int]:
    """Every match of one season, newest first - the order the window logic expects."""
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT id FROM match WHERE season_number = ? ORDER BY start DESC, id DESC",
            (season,),
        ).fetchall()
    return [row[0] for row in rows]


def current_season() -> int | None:
    """The season the ranking defaults to.

    By date first, so ``broom`` agrees with the rest of ``stats`` about what "current"
    means. A season that has started on the calendar but holds no match yet would
    produce an empty list, so it falls back to the season the newest match belongs to -
    the season actually being played.
    """
    today = date.today().isoformat()
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT number FROM season
            WHERE start <= ?
              AND EXISTS (SELECT 1 FROM match WHERE match.season_number = season.number)
            ORDER BY start DESC LIMIT 1
            """,
            (today,),
        ).fetchone()
        if row:
            return row[0]
        row = conn.execute(
            "SELECT season_number FROM match ORDER BY start DESC, id DESC LIMIT 1"
        ).fetchone()
    return row[0] if row else None


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


def fetch_km_for_weeks(
    player_ids: list[int], weeks: list[tuple[int, int]]
) -> dict[int, tuple[float, int, int]]:
    """Average per week, weeks read, and the total over exactly the weeks the window
    covers.

    The average is what ranks - it stays fair when one player has fewer weeks on
    record - while the total is what the table shows, because "820 km im Monat" is a
    number a leader can hold against somebody and "205 km/Woche" is not.

    Deliberately *not* the rolling ``DISTANCE_AVERAGE_WINDOW`` that ``player show``
    and the kilometre ranking use: those describe current form across seasons, while
    broom judges one season and every one of its numbers has to come from it. The
    count is returned with the average because a single week is not a motivation.
    """
    if not player_ids or not weeks:
        return {}

    players = ",".join("?" * len(player_ids))
    pairs = " OR ".join(["(d.year = ? AND d.week = ?)"] * len(weeks))
    flat_weeks = [value for week in weeks for value in week]
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT d.player_id, AVG(d.km), COUNT(*), SUM(d.km)
            FROM distance d
            WHERE d.player_id IN ({players}) AND ({pairs})
            GROUP BY d.player_id
            """,
            (*player_ids, *flat_weeks),
        ).fetchall()
    return {
        row[0]: (float(row[1] or 0.0), int(row[2] or 0), int(row[3] or 0)) for row in rows
    }


def season_bounds(season: int) -> tuple[str, str] | None:
    """First and last day of a season - it ends where the next one starts.

    A season still running has no successor, so it ends today: the kilometres it is
    judged on are the ones actually driven so far.
    """
    with connect_db() as conn:
        row = conn.execute("SELECT start FROM season WHERE number = ?", (season,)).fetchone()
        if not row:
            return None
        start = row[0][:10]
        following = conn.execute(
            "SELECT start FROM season WHERE start > ? ORDER BY start LIMIT 1", (start,)
        ).fetchone()
    if following:
        last = (date.fromisoformat(following[0][:10]) - timedelta(days=1)).isoformat()
    else:
        last = date.today().isoformat()
    return start, max(start, last)


def match_bounds(match_ids: list[int]) -> tuple[str, str] | None:
    """Oldest and newest match day in the window - the period a ``--last`` run covers."""
    if not match_ids:
        return None
    placeholders = ",".join("?" * len(match_ids))
    with connect_db() as conn:
        row = conn.execute(
            f"SELECT MIN(start), MAX(start) FROM match WHERE id IN ({placeholders})",
            tuple(match_ids),
        ).fetchone()
    if not row or not row[0]:
        return None
    return row[0][:10], row[1][:10]


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
