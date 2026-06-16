from __future__ import annotations

from hcr2.models.vehicle import Vehicle
from hcr2.repositories import vehicles as vehicle_repo


def list_vehicles() -> list[Vehicle]:
    return vehicle_repo.list_vehicles()


def add_vehicle(name: str, shortname: str) -> None:
    vehicle_repo.add_vehicle(name, shortname)


def edit_vehicle(vehicle_id: int, *, name: str | None = None, shortname: str | None = None) -> bool:
    if not name and not shortname:
        return False
    vehicle_repo.update_vehicle(vehicle_id, name=name, shortname=shortname)
    return True


def delete_vehicle(vehicle_id: int) -> None:
    vehicle_repo.delete_vehicle(vehicle_id)


def import_vehicles(rows: list[dict[str, object]]) -> int:
    return vehicle_repo.add_new_vehicles(rows)


def export_vehicles() -> list[dict[str, str]]:
    return [
        {"name": vehicle.name, "shortname": vehicle.shortname}
        for vehicle in vehicle_repo.list_vehicles_by_name()
    ]


def drop_vehicle_table() -> None:
    vehicle_repo.drop_vehicle_table()

