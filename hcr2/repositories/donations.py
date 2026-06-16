from __future__ import annotations

from hcr2.db.connection import connect_db
from hcr2.models.donation import DonationDateEntry, DonationDateSummary, DonationEntry


def upsert_donation(player_id: int, date: str, total: int) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO donation (player_id, date, total)
            VALUES (?, ?, ?)
            ON CONFLICT(player_id, date) DO UPDATE SET total = excluded.total
            """,
            (player_id, date, total),
        )


def delete_donation(donation_id: int) -> int:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM donation WHERE id = ?", (donation_id,))
        return cur.rowcount


def get_donation(donation_id: int) -> tuple[int, str, int] | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT player_id, date, total
            FROM donation
            WHERE id = ?
            """,
            (donation_id,),
        )
        return cur.fetchone()


def update_total(donation_id: int, total: int) -> int:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE donation SET total = ? WHERE id = ?", (total, donation_id))
        return cur.rowcount


def get_player_name(player_id: int) -> str | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM players WHERE id = ?", (player_id,))
        row = cur.fetchone()
        return row[0] if row else None


def list_player_donations(player_id: int) -> list[DonationEntry]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, date, total FROM donation
            WHERE player_id = ?
            ORDER BY date ASC
            """,
            (player_id,),
        )
        return [DonationEntry(id=row[0], date=row[1], total=row[2]) for row in cur.fetchall()]


def list_active_players() -> list[tuple[int, str]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM players WHERE active = 1")
        return cur.fetchall()


def list_player_totals(player_id: int) -> list[DonationEntry]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT date, total FROM donation
            WHERE player_id = ?
            ORDER BY date ASC
            """,
            (player_id,),
        )
        return [DonationEntry(id=None, date=row[0], total=row[1]) for row in cur.fetchall()]


def get_latest_donation_date() -> str | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(date) FROM donation")
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None


def list_active_plte_players() -> list[tuple[int, str]]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM players "
            "WHERE active = 1 AND team = 'PLTE' "
            "ORDER BY id"
        )
        return cur.fetchall()


def count_player_matches_between(player_id: int, start_date: str, cutoff_date: str) -> int:
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
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else 0


def get_player_latest_total(player_id: int, cutoff_date: str) -> int:
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


def list_donation_dates() -> list[DonationDateSummary]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT date, COUNT(*) AS cnt
            FROM donation
            GROUP BY date
            ORDER BY date ASC
            """
        )
        return [DonationDateSummary(date=row[0], count=row[1]) for row in cur.fetchall()]


def list_donations_for_date(date: str) -> list[DonationDateEntry]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.id, d.player_id, p.name, IFNULL(p.team, ''), d.total
            FROM donation d
            LEFT JOIN players p ON p.id = d.player_id
            WHERE d.date = ?
            ORDER BY p.team, p.name, d.player_id
            """,
            (date,),
        )
        return [
            DonationDateEntry(id=row[0], player_id=row[1], player_name=row[2], team=row[3], total=row[4])
            for row in cur.fetchall()
        ]
