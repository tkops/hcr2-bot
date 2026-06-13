from __future__ import annotations

import datetime
import sqlite3
from typing import Any

from hcr2.db.connection import connect_db


def find_current_season() -> int | None:
    today = datetime.date.today().isoformat()
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT number FROM season WHERE start <= ? ORDER BY start DESC LIMIT 1", (today,))
        row = cur.fetchone()
        return row[0] if row else None


def get_season_meta(season_number: int) -> tuple[str, str]:
    name = ""
    division = ""
    with connect_db() as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT name, division FROM season WHERE number = ?", (season_number,))
            row = cur.fetchone()
            if row:
                name = row[0] or ""
                division = row[1] or ""
        except sqlite3.OperationalError:
            pass
    return name, division


def fetch_season_rows(season_number: int) -> list[tuple[Any, ...]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                ms.player_id,
                p.name,
                p.alias,
                p.team,
                p.active,
                ms.score,
                ms.points,
                ms.absent,
                m.id,
                t.tracks,
                t.max_score_per_track
            FROM matchscore ms
            JOIN players   p ON ms.player_id = p.id
            JOIN match     m ON ms.match_id = m.id
            JOIN teamevent t ON m.teamevent_id = t.id
            WHERE m.season_number = ?
            """,
            (season_number,),
        )
        return cur.fetchall()


def get_min_required_matches(season_number: int, ratio: float = 0.20) -> tuple[int, int]:
    import math

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM match WHERE season_number = ?", (season_number,))
        total_matches = int(cur.fetchone()[0] or 0)

    if total_matches <= 0:
        return 0, 0

    min_required = math.ceil(total_matches * ratio)
    return total_matches, min_required


def list_active_plte_players() -> list[tuple[int, str]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM players WHERE active = 1 AND team = 'PLTE'")
        return cur.fetchall()


def list_active_plte_player_ids() -> set[int]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM players WHERE active = 1 AND team = 'PLTE'")
        return {row[0] for row in cur.fetchall()}


def fetch_unexcused_absences(season_number: int) -> list[tuple[int, str, int]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT p.id, p.name, COUNT(ms.id) AS unexcused
            FROM matchscore ms
            JOIN match m   ON ms.match_id = m.id
            JOIN players p ON ms.player_id = p.id
            WHERE m.season_number = ?
              AND p.active = 1
              AND UPPER(p.team) = 'PLTE'
              AND (ms.absent IS NULL OR ms.absent = 0)
              AND ms.points = 0
            GROUP BY p.id, p.name
            ORDER BY unexcused DESC, p.name ASC
            """,
            (season_number,),
        )
        return cur.fetchall()


def resolve_teamevent_by_offset(offset: int) -> int | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT t.id, t.name, t.iso_year, t.iso_week
            FROM teamevent t
            JOIN match m ON m.teamevent_id = t.id
            ORDER BY t.iso_year DESC, t.iso_week DESC, t.id DESC
            """
        )
        rows = cur.fetchall()
    if not rows:
        return None
    if offset < 0 or offset >= len(rows):
        return None
    return rows[offset][0]


def get_teamevent_meta(te_id: int) -> tuple[Any, ...] | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, iso_year, iso_week, tracks, max_score_per_track
            FROM teamevent
            WHERE id = ?
            """,
            (te_id,),
        )
        return cur.fetchone()


def fetch_teamevent_rows(te_id: int) -> list[tuple[Any, ...]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                ms.player_id,
                p.name,
                p.team,
                p.active,
                ms.score,
                ms.points,
                ms.absent,
                m.id AS match_id,
                t.tracks,
                t.max_score_per_track
            FROM matchscore ms
            JOIN players   p ON ms.player_id = p.id
            JOIN match     m ON ms.match_id = m.id
            JOIN teamevent t ON m.teamevent_id = t.id
            WHERE m.teamevent_id = ?
            """,
            (te_id,),
        )
        return cur.fetchall()


def fetch_avg_score_last_seasons(last_n: int = 20) -> list[tuple[Any, ...]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.season_number,
                   AVG( ms.score * 4.0 / NULLIF(t.tracks, 0) ) AS avg_scaled
            FROM matchscore ms
            JOIN match     m ON m.id = ms.match_id
            JOIN teamevent t ON t.id = m.teamevent_id
            JOIN players   p ON p.id = ms.player_id
            WHERE ms.score IS NOT NULL
              AND NOT (IFNULL(ms.absent,0)=1 AND IFNULL(ms.score,0)=0)
              AND p.team = 'PLTE'
              AND p.active = 1
            GROUP BY m.season_number
            ORDER BY m.season_number DESC
            LIMIT ?
            """,
            (last_n,),
        )
        rows = cur.fetchall()
    rows.reverse()
    return rows


def fetch_birthday_plot_rows() -> list[tuple[Any, ...]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, birthday, COALESCE(emoji,'')
            FROM players
            WHERE birthday IS NOT NULL AND birthday <> ''
            """
        )
        return cur.fetchall()


def fetch_season_matches(season_number: int) -> list[tuple[Any, ...]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.id, m.start
            FROM match m
            WHERE m.season_number = ?
            ORDER BY m.start ASC
            """,
            (season_number,),
        )
        return cur.fetchall()


def fetch_player_meta_for_ids(player1_id: int, player2_id: int) -> dict[int, tuple[str, str]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, COALESCE(emoji,'') FROM players WHERE id IN (?,?)",
            (player1_id, player2_id),
        )
        return {player_id: (name, emoji or "") for player_id, name, emoji in cur.fetchall()}


def fetch_matchscores_for_matches_players(match_ids: list[int], player1_id: int, player2_id: int) -> list[tuple[Any, ...]]:
    if not match_ids:
        return []

    with connect_db() as conn:
        cur = conn.cursor()
        query = """
            SELECT ms.match_id, ms.player_id, ms.score, ms.points, ms.absent
            FROM matchscore ms
            WHERE ms.match_id IN ({})
              AND ms.player_id IN (?,?)
        """.format(",".join("?" * len(match_ids)))
        cur.execute(query, match_ids + [player1_id, player2_id])
        return cur.fetchall()


def get_player_stats_meta(player_id: int) -> tuple[Any, ...] | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT name, COALESCE(emoji,''), COALESCE(team,''), active, COALESCE(garage_power, 0)
            FROM players
            WHERE id = ?
            """,
            (player_id,),
        )
        return cur.fetchone()


def count_player_matchscores(player_id: int) -> int:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM matchscore WHERE player_id = ?", (player_id,))
        return int(cur.fetchone()[0] or 0)


def count_player_unexcused_absences(player_id: int) -> int:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*)
            FROM matchscore
            WHERE player_id = ?
              AND (score IS NULL OR score = 0)
              AND (points IS NULL OR points = 0)
              AND (absent IS NULL OR absent = 0)
            """,
            (player_id,),
        )
        return int(cur.fetchone()[0] or 0)


def fetch_player_last_matches(player_id: int, last_n: int) -> list[tuple[Any, ...]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                m.id,
                m.start,
                m.season_number,
                t.name,
                t.tracks,
                ms.score,
                ms.points,
                ms.absent
            FROM matchscore ms
            JOIN match     m ON m.id = ms.match_id
            JOIN teamevent t ON t.id = m.teamevent_id
            WHERE ms.player_id = ?
            ORDER BY m.start DESC, m.id DESC
            LIMIT ?
            """,
            (player_id, last_n),
        )
        return cur.fetchall()


def fetch_player_overall_matches(player_id: int) -> list[tuple[Any, ...]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                m.id,
                m.start,
                t.tracks,
                ms.score,
                ms.points,
                ms.absent
            FROM matchscore ms
            JOIN match     m ON m.id = ms.match_id
            JOIN teamevent t ON t.id = m.teamevent_id
            WHERE ms.player_id = ?
            ORDER BY m.start ASC, m.id ASC
            """,
            (player_id,),
        )
        return cur.fetchall()


def fetch_match_rows_for_medians(match_ids: list[int]) -> list[tuple[Any, ...]]:
    if not match_ids:
        return []

    rows: list[tuple[Any, ...]] = []
    with connect_db() as conn:
        cur = conn.cursor()
        for i in range(0, len(match_ids), 900):
            chunk = match_ids[i:i + 900]
            query = f"""
                SELECT
                    ms.match_id,
                    ms.score,
                    ms.points,
                    ms.absent,
                    p.team,
                    t.tracks
                FROM matchscore ms
                JOIN players   p ON p.id = ms.player_id
                JOIN match     m ON m.id = ms.match_id
                JOIN teamevent t ON t.id = m.teamevent_id
                WHERE ms.match_id IN ({",".join("?" * len(chunk))})
            """
            cur.execute(query, chunk)
            rows.extend(cur.fetchall())
    return rows


def get_latest_donation_date() -> str | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM donation")
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None


def count_player_donation_matches(player_id: int, start_date: str, cutoff_date: str) -> int:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(DISTINCT m.id)
            FROM match m
            JOIN matchscore ms ON ms.match_id = m.id
            WHERE ms.player_id = ?
              AND DATE(m.start) >= DATE(?)
              AND DATE(m.start) <= DATE(?)
            """,
            (player_id, start_date, cutoff_date),
        )
        return int(cur.fetchone()[0] or 0)


def get_player_latest_donation_total(player_id: int, cutoff_date: str) -> int:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT total FROM donation
            WHERE player_id = ?
              AND date <= ?
            ORDER BY date DESC LIMIT 1
            """,
            (player_id, cutoff_date),
        )
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
