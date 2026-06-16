from __future__ import annotations

import sqlite3
from typing import Iterable

from hcr2.db.connection import connect_db
from hcr2.models.vehicle import Vehicle


def list_vehicles() -> list[Vehicle]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, shortname FROM vehicle ORDER BY id")
        return [Vehicle(id=row[0], name=row[1], shortname=row[2]) for row in cur.fetchall()]


def list_vehicles_by_name() -> list[Vehicle]:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, shortname FROM vehicle ORDER BY name COLLATE NOCASE")
        return [Vehicle(id=row[0], name=row[1], shortname=row[2]) for row in cur.fetchall()]


def add_vehicle(name: str, shortname: str) -> None:
    with connect_db() as conn:
        conn.execute(
            "INSERT INTO vehicle (name, shortname) VALUES (?, ?)",
            (name, shortname),
        )


def update_vehicle(vehicle_id: int, *, name: str | None = None, shortname: str | None = None) -> None:
    fields = []
    values: list[object] = []
    if name:
        fields.append("name = ?")
        values.append(name)
    if shortname:
        fields.append("shortname = ?")
        values.append(shortname)
    if not fields:
        return

    values.append(vehicle_id)
    with connect_db() as conn:
        conn.execute(f"UPDATE vehicle SET {', '.join(fields)} WHERE id = ?", values)


def delete_vehicle(vehicle_id: int) -> None:
    with connect_db() as conn:
        conn.execute("DELETE FROM vehicle WHERE id = ?", (vehicle_id,))


def add_new_vehicles(rows: Iterable[dict[str, object]]) -> int:
    count = 0
    with connect_db() as conn:
        for row in rows:
            try:
                conn.execute(
                    "INSERT INTO vehicle (name, shortname) VALUES (?, ?)",
                    (row["name"], row["shortname"]),
                )
                count += 1
            except sqlite3.IntegrityError:
                pass
    return count


def drop_vehicle_table() -> None:
    with connect_db() as conn:
        conn.execute("DROP TABLE IF EXISTS vehicle;")
