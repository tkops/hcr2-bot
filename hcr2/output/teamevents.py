from __future__ import annotations

from hcr2.models.teamevent import TeamEvent, TeamEventVehicle


def print_teamevent_list(events: list[TeamEvent]) -> None:
    print(f"{'ID.':>4} {'Year':<6} {'Wk':<4}  {'Name'}")
    print("-" * 40)
    for event in events:
        print(f"{event.id:>3}. {event.iso_year:<6} {event.iso_week:<4}  {event.name}")


def print_teamevent_summary_list(events: list[TeamEvent]) -> None:
    print(f"{'ID.':>4} {'Year':<6} {'Wk':<4}  {'Name':<25}  {'Tracks':<6}  {'Score/Track':<12}")
    print("-" * 70)
    for event in events:
        print(
            f"{event.id:>3}. {event.iso_year:<6} {event.iso_week:<4}  "
            f"{event.name:<25}  {event.tracks:<6}  {event.max_score_per_track:<12}"
        )


def print_teamevent_detail(event: TeamEvent, vehicles: list[TeamEventVehicle]) -> None:
    print(f"\nTeam event {event.id}:")
    print(f"  Name         : {event.name}")
    print(f"  Year/Wk      : {event.iso_year}/W{event.iso_week}")
    print(f"  Tracks       : {event.tracks}")
    print(f"  Score/Track  : {event.max_score_per_track}")
    print(f"  Vehicles     :")
    if vehicles:
        for vehicle in vehicles:
            print(f"    - {vehicle.id}: {vehicle.name}")
    else:
        print("    (none)")

