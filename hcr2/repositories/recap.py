"""SQL for the match recap.

Two things shape the queries here. The history questions ("how often was this player on
the podium", "was that their best run ever") are asked for the whole roster at once, so they
are window functions over one result set rather than one query per player - the recap
runs right after `video apply`, where nobody wants to wait.

And every "before this match" is ordered by ``(start, id)``, not by id alone: matches
are imported out of order often enough that the id is not a timeline.
"""
from __future__ import annotations

from hcr2.db.connection import connect_db


PODIUM_PLACES = 3


def fetch_match_rows(match_id: int) -> list[tuple[int, str, int, int, int, int]]:
    """(player_id, name, score, points, absent, checkin) for every row of the match."""
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ms.player_id, p.name, ms.score, ms.points,
                   COALESCE(ms.absent, 0), COALESCE(ms.checkin, 0)
            FROM matchscore ms
            JOIN players p ON p.id = ms.player_id
            WHERE ms.match_id = ?
            ORDER BY ms.score DESC, ms.player_id ASC
            """,
            (match_id,),
        )
        return [tuple(row) for row in cur.fetchall()]


def get_event_tracks(teamevent_id: int) -> int:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT tracks FROM teamevent WHERE id = ?", (teamevent_id,))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] else 0


def previous_match_ids(start: str, match_id: int, limit: int) -> list[int]:
    """The `limit` matches immediately before this one, newest first."""
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM match
            WHERE start < ? OR (start = ? AND id < ?)
            ORDER BY start DESC, id DESC
            LIMIT ?
            """,
            (start, start, match_id, limit),
        )
        return [int(row[0]) for row in cur.fetchall()]


def podium_by_match(match_ids: list[int]) -> dict[int, list[int]]:
    """match_id -> the player ids of its top three, best first."""
    if not match_ids:
        return {}
    placeholders = ",".join("?" for _ in match_ids)
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT match_id, player_id FROM (
                SELECT ms.match_id, ms.player_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY ms.match_id
                           ORDER BY ms.score DESC, ms.player_id ASC
                       ) AS place
                FROM matchscore ms
                WHERE ms.match_id IN ({placeholders}) AND ms.score > 0
            )
            WHERE place <= ?
            ORDER BY match_id, place
            """,
            (*match_ids, PODIUM_PLACES),
        )
        result: dict[int, list[int]] = {}
        for match_id, player_id in cur.fetchall():
            result.setdefault(int(match_id), []).append(int(player_id))
        return result


def count_podiums_ever(player_ids: list[int], start: str, match_id: int) -> dict[int, int]:
    """How many podiums each player had in their whole history before this match.

    Only asked for the three who are standing there now, but computed over every match -
    "first podium ever" is a claim that a 20-match window cannot support.
    """
    if not player_ids:
        return {}
    placeholders = ",".join("?" for _ in player_ids)
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT player_id, COUNT(*) FROM (
                SELECT ms.player_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY ms.match_id
                           ORDER BY ms.score DESC, ms.player_id ASC
                       ) AS place
                FROM matchscore ms
                JOIN match m ON m.id = ms.match_id
                WHERE ms.score > 0
                  AND (m.start < ? OR (m.start = ? AND m.id < ?))
            )
            WHERE place <= ? AND player_id IN ({placeholders})
            GROUP BY player_id
            """,
            (start, start, match_id, PODIUM_PLACES, *player_ids),
        )
        return {int(pid): int(count) for pid, count in cur.fetchall()}


def previous_scores(start: str, match_id: int, limit: int) -> dict[int, list[int]]:
    """player_id -> the last `limit` driven scores before this match, newest first."""
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT player_id, score FROM (
                SELECT ms.player_id, ms.score,
                       ROW_NUMBER() OVER (
                           PARTITION BY ms.player_id
                           ORDER BY m.start DESC, m.id DESC
                       ) AS rn
                FROM matchscore ms
                JOIN match m ON m.id = ms.match_id
                WHERE ms.score > 0
                  AND (m.start < ? OR (m.start = ? AND m.id < ?))
            )
            WHERE rn <= ?
            ORDER BY player_id, rn
            """,
            (start, start, match_id, limit),
        )
        result: dict[int, list[int]] = {}
        for player_id, score in cur.fetchall():
            result.setdefault(int(player_id), []).append(int(score))
        return result


def personal_bests(start: str, match_id: int) -> dict[int, tuple[int, int]]:
    """player_id -> (best score so far, number of driven matches so far)."""
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ms.player_id, MAX(ms.score), COUNT(*)
            FROM matchscore ms
            JOIN match m ON m.id = ms.match_id
            WHERE ms.score > 0
              AND (m.start < ? OR (m.start = ? AND m.id < ?))
            GROUP BY ms.player_id
            """,
            (start, start, match_id),
        )
        return {int(pid): (int(best), int(count)) for pid, best, count in cur.fetchall()}


def event_matches(teamevent_id: int) -> list[tuple[int, str, str, int, int, int, int]]:
    """Every match of the event: (id, start, opponent, ladys, opponent_score, sum, drivers)."""
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.id, m.start, m.opponent, m.score_ladys, m.score_opponent,
                   COALESCE((SELECT SUM(score) FROM matchscore WHERE match_id = m.id), 0),
                   (SELECT COUNT(*) FROM matchscore WHERE match_id = m.id AND score > 0)
            FROM match m
            WHERE m.teamevent_id = ?
            ORDER BY m.start, m.id
            """,
            (teamevent_id,),
        )
        return [tuple(row) for row in cur.fetchall()]


def opponent_history(opponent: str, match_id: int) -> list[tuple[int, str, int, int]]:
    """Earlier meetings with the same opponent, oldest first."""
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, start, score_ladys, score_opponent
            FROM match
            WHERE opponent = ? AND id != ?
            ORDER BY start, id
            """,
            (opponent, match_id),
        )
        return [tuple(row) for row in cur.fetchall()]


def season_record(season_number: int, start: str, match_id: int) -> tuple[int, int]:
    """(wins, matches) of the season up to and including this match."""
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN score_ladys > score_opponent THEN 1 ELSE 0 END), 0),
                   COUNT(*)
            FROM match
            WHERE season_number = ?
              AND (start < ? OR (start = ? AND id <= ?))
            """,
            (season_number, start, start, match_id),
        )
        wins, total = cur.fetchone()
        return int(wins), int(total)
