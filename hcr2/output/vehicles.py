from __future__ import annotations

from hcr2.models.vehicle import Vehicle
from hcr2.output.tables import print_table


def print_vehicles(vehicles: list[Vehicle]) -> None:
    print_table(
        headers=[f"{'ID':<2}", f"{'Name':<18}", "SN"],
        rows=[
            [f"{vehicle.id:>2}.", f"{vehicle.name:<18}", vehicle.shortname]
            for vehicle in vehicles
        ],
        width=26,
    )

