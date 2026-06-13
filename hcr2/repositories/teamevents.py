from __future__ import annotations

import sqlite3

from hcr2.db.connection import connect_db
from hcr2.models.teamevent import TeamEvent, TeamEventVehicle


def latest_iso_week() -> tuple[int, int] | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT iso_year, iso_week
            FROM teamevent
            ORDER BY iso_year DESC, iso_week DESC, id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return (int(row[0]), int(row[1])) if row else None


def resolve_vehicle_id(token: str, *, allow_name_lookup: bool = False) -> int | None:
    if token.isdigit():
        return int(token)

    if allow_name_lookup:
        query = """
            SELECT id
            FROM vehicle
            WHERE LOWER(shortname) = LOWER(?)
               OR LOWER(name) = LOWER(?)
            ORDER BY id
            LIMIT 1
        """
        params = (token, token)
    else:
        query = "SELECT id FROM vehicle WHERE shortname = ?"
        params = (token,)

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
        return row[0] if row else None


def add_teamevent(
    *,
    name: str,
    iso_year: int,
    iso_week: int,
    tracks: int,
    max_score_per_track: int,
    vehicle_ids: list[int],
) -> tuple[int | None, list[int]]:
    invalid_vehicle_ids: list[int] = []
    with connect_db() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO teamevent (name, iso_year, iso_week, tracks, max_score_per_track)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, iso_year, iso_week, tracks, max_score_per_track),
            )
            teamevent_id = cur.lastrowid

            for vehicle_id in vehicle_ids:
                try:
                    cur.execute(
                        "INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (?, ?)",
                        (teamevent_id, vehicle_id),
                    )
                except sqlite3.IntegrityError:
                    invalid_vehicle_ids.append(vehicle_id)

            conn.commit()
            return teamevent_id, invalid_vehicle_ids
        except sqlite3.IntegrityError:
            return None, invalid_vehicle_ids


def list_latest(limit: int = 10) -> list[TeamEvent]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, iso_year, iso_week, tracks, max_score_per_track
            FROM teamevent
            ORDER BY iso_year DESC, iso_week DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_event_from_row(row) for row in cur.fetchall()]


def list_all() -> list[TeamEvent]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, iso_year, iso_week, tracks, max_score_per_track
            FROM teamevent
            ORDER BY iso_year DESC, iso_week DESC
            """
        )
        return [_event_from_row(row) for row in cur.fetchall()]


def get_teamevent(teamevent_id: int) -> TeamEvent | None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, iso_year, iso_week, tracks, max_score_per_track
            FROM teamevent WHERE id = ?
            """,
            (teamevent_id,),
        )
        row = cur.fetchone()
        return _event_from_row(row) if row else None


def list_event_vehicles(teamevent_id: int) -> list[TeamEventVehicle]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT v.id, v.name
            FROM teamevent_vehicle tv
            JOIN vehicle v ON tv.vehicle_id = v.id
            WHERE tv.teamevent_id = ?
            ORDER BY v.id
            """,
            (teamevent_id,),
        )
        return [TeamEventVehicle(id=row[0], name=row[1]) for row in cur.fetchall()]


def update_teamevent(teamevent_id: int, updates: dict[str, object]) -> int:
    if not updates:
        return 0
    fields = [f"{column} = ?" for column in updates]
    values = list(updates.values()) + [teamevent_id]
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE teamevent SET {', '.join(fields)} WHERE id = ?", values)
        return cur.rowcount


def replace_event_vehicles(teamevent_id: int, vehicle_ids: list[int]) -> list[int]:
    warnings: list[int] = []
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (teamevent_id,))
        for vehicle_id in vehicle_ids:
            try:
                cur.execute(
                    "INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (?, ?)",
                    (teamevent_id, vehicle_id),
                )
            except sqlite3.IntegrityError:
                warnings.append(vehicle_id)
    return warnings


def clear_event_vehicles(teamevent_id: int) -> None:
    with connect_db() as conn:
        conn.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (teamevent_id,))


def delete_teamevent(teamevent_id: int) -> None:
    with connect_db() as conn:
        conn.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (teamevent_id,))
        conn.execute("DELETE FROM teamevent WHERE id = ?", (teamevent_id,))


def _event_from_row(row) -> TeamEvent:
    return TeamEvent(
        id=row[0],
        name=row[1],
        iso_year=row[2],
        iso_week=row[3],
        tracks=row[4],
        max_score_per_track=row[5],
    )

