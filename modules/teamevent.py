from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Optional

from hcr2.output.teamevents import (
    print_teamevent_detail,
    print_teamevent_list,
    print_teamevent_summary_list,
)
from hcr2.repositories import teamevents as teamevent_repo
from modules.common import (
    get_arg_value,
    is_help_request,
    parse_flag_map,
    parse_int,
    print_command_help,
    print_unknown_command,
)


USAGE_ADD = (
    'Usage: teamevent add "<name>" [<year>/W<week>] [vehicle_ids|vehicle_shortnames] [track-count] [max-score] '
    '| --name <name> [--week <year>/W<week>] [--vehicles 1,2,3|codes] [--tracks <num>] [--score <num>]'
)
USAGE_DELETE = "Usage: teamevent delete <id> | --id <id>"
USAGE_SHOW = "Usage: teamevent show all | <id> | --all | --id <id>"
USAGE_EDIT = "Usage: teamevent edit <id> [--name NAME] [--tracks NUM] [--vehicles 1,2,3|codes] [--score SCORE] | --id <id> [--name NAME] [--tracks NUM] [--vehicles 1,2,3|codes] [--score SCORE]"


def handle_command(cmd: str, args: list[str]) -> None:
    if is_help_request(cmd, *args):
        print_help()
        return

    handlers: dict[str, Callable[[list[str]], None]] = {
        "add": _handle_add,
        "list": _handle_list,
        "edit": _handle_edit,
        "delete": _handle_delete,
        "show": _handle_show,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print_unknown_command("teamevent", cmd)
        print_help()
        return
    handler(args)


def print_help() -> None:
    print_command_help(
        usage="hcr2.py teamevent <command> [options]",
        commands=[
            ("add --name <name> [--week <year>/W<week>] [--vehicles <ids|codes>] [--tracks <num>] [--score <num>]", "Add one team event"),
            ("list", "Show the latest 10 team events"),
            ("list --all", "Show all team events"),
            ("show --all", "Show all team events with summary fields"),
            ("show --id <id>", "Show one team event"),
            ("edit --id <id> [--name NAME] [--tracks NUM] [--vehicles 1,2,3] [--score SCORE]", "Edit one team event"),
            ("delete --id <id>", "Delete one team event"),
        ],
        notes=[
            "Default week for add is the next free ISO week.",
            "Legacy positional aliases are still accepted for add, show, edit and delete.",
        ],
        examples=[
            'teamevent add --name "Teamcup" --week 2025/W38',
            'teamevent add --name "Teamcup" --week 2025/W38 --vehicles be,ro,sm,sc,hc --tracks 5 --score 15000',
        ],
    )


def _handle_add(args: list[str]) -> None:
    add_teamevent(args)


def _handle_list(args: list[str]) -> None:
    if args == ["--all"]:
        show_teamevent(["all"])
        return
    if args:
        print("Usage: teamevent list")
        return
    list_teamevents()


def _handle_edit(args: list[str]) -> None:
    edit_teamevent(args)


def _handle_delete(args: list[str]) -> None:
    teamevent_id = _extract_teamevent_id(args)
    if teamevent_id is None:
        print(USAGE_DELETE)
        return
    delete_teamevent(teamevent_id)


def _handle_show(args: list[str]) -> None:
    show_teamevent(args)


def _parse_iso_week_token(value: str) -> tuple[Optional[int], Optional[int]]:
    try:
        year_str, week_str = value.replace("W", "").split("/")
        return int(year_str), int(week_str)
    except (AttributeError, TypeError, ValueError):
        return None, None


def _next_free_iso_week() -> tuple[int, int]:
    latest = teamevent_repo.latest_iso_week()
    if latest is None:
        next_week = date.today() + timedelta(days=7)
        iso_year, iso_week, _ = next_week.isocalendar()
        return iso_year, iso_week

    latest_year, latest_week = latest
    next_monday = date.fromisocalendar(latest_year, latest_week, 1) + timedelta(days=7)
    iso_year, iso_week, _ = next_monday.isocalendar()
    return iso_year, iso_week


def _resolve_vehicle_inputs(
    tokens: list[str],
    *,
    allow_name_lookup: bool = False,
) -> tuple[list[int], list[str]]:
    resolved_ids: list[int] = []
    warnings: list[str] = []

    for token in tokens:
        vehicle_id = None
        if token.isdigit():
            vehicle_id = int(token)
        else:
            vehicle_id = teamevent_repo.resolve_vehicle_id(token, allow_name_lookup=allow_name_lookup)

        if vehicle_id is None:
            warnings.append(token)
        else:
            resolved_ids.append(vehicle_id)

    seen = set()
    deduped_ids = [vid for vid in resolved_ids if not (vid in seen or seen.add(vid))]
    return deduped_ids, warnings


def _parse_edit_args(args: list[str]) -> tuple[Optional[int], Optional[str], Optional[int], Optional[int], Optional[str], bool]:
    teamevent_id = _extract_teamevent_id(args)
    if teamevent_id is None:
        print(USAGE_EDIT)
        return None, None, None, None, None, False

    flag_args = args[2:] if args and args[0] == "--id" else args[1:]
    flags = parse_flag_map(flag_args)
    name = flags.get("name")
    tracks = parse_int(flags.get("tracks")) if "tracks" in flags else None
    max_score = parse_int(flags.get("score")) if "score" in flags else None
    vehicles_arg = flags.get("vehicles")

    if "tracks" in flags and tracks is None:
        print(USAGE_EDIT)
        return None, None, None, None, None, False
    if "score" in flags and max_score is None:
        print(USAGE_EDIT)
        return None, None, None, None, None, False
    if vehicles_arg is not None:
        vehicles_arg = vehicles_arg.strip()

    return teamevent_id, name, tracks, max_score, vehicles_arg, True


def _extract_teamevent_id(args: list[str]) -> Optional[int]:
    if not args:
        return None
    if args[0] == "--id":
        return parse_int(args[1]) if len(args) > 1 else None
    return parse_int(args[0])


def add_teamevent(args: list[str]) -> None:
    if args and args[0].startswith("--"):
        flags = parse_flag_map(args)
        name = flags.get("name")
        week_token = flags.get("week")
        if not name:
            print(USAGE_ADD)
            return

        args = [name]
        if week_token:
            args.append(week_token)

        tail: list[str] = []
        if "vehicles" in flags:
            tail.append(flags["vehicles"])
        if "tracks" in flags:
            tail.append(flags["tracks"])
        if "score" in flags:
            tail.append(flags["score"])
        args.extend(tail)

    if not args:
        print(USAGE_ADD)
        return

    name = args[0]
    tracks = 4
    max_score = 15000
    vehicle_inputs: list[str] = []
    tail = args[1:]

    iso_year = None
    iso_week = None
    if tail:
        parsed_year, parsed_week = _parse_iso_week_token(tail[0])
        if parsed_year is not None and parsed_week is not None:
            iso_year, iso_week = parsed_year, parsed_week
            tail = tail[1:]
        elif any(ch.isdigit() for ch in tail[0]) and ("/" in tail[0] or "W" in tail[0] or "-" in tail[0]):
            print("❌ Invalid year/week format. Example: 2025/30 or 2025/W30")
            return

    if iso_year is None or iso_week is None:
        iso_year, iso_week = _next_free_iso_week()

    if tail and tail[-1].isdigit():
        max_score = int(tail.pop())
    if tail and tail[-1].isdigit():
        tracks = int(tail.pop())
    if tail:
        vehicle_inputs = [v.strip() for v in tail[0].split(",") if v.strip()]

    resolved_ids, warnings = _resolve_vehicle_inputs(vehicle_inputs, allow_name_lookup=False)

    for token in warnings:
        print(f"⚠️  Vehicle '{token}' not found (neither ID nor shortname).")

    teamevent_id, invalid_ids = teamevent_repo.add_teamevent(
        name=name,
        iso_year=iso_year,
        iso_week=iso_week,
        tracks=tracks,
        max_score_per_track=max_score,
        vehicle_ids=resolved_ids,
    )
    if teamevent_id is None:
        print(f"❌ Team event for week {iso_week}/{iso_year} already exists.")
        return

    for vehicle_id in invalid_ids:
        print(f"⚠️  Vehicle ID {vehicle_id} does not exist or is already linked.")

    print("✅ Team event added:")
    show_teamevent([str(teamevent_id)])


def list_teamevents() -> None:
    print_teamevent_list(teamevent_repo.list_latest())


def show_teamevent(args: list[str]) -> None:
    if not args:
        print(USAGE_SHOW)
        return

    if args[0] == "all" or args == ["--all"]:
        print_teamevent_summary_list(teamevent_repo.list_all())
        return

    teamevent_id = _extract_teamevent_id(args)
    if teamevent_id is None:
        print(USAGE_SHOW)
        return

    event = teamevent_repo.get_teamevent(teamevent_id)
    if event is None:
        print(f"❌ Team event {teamevent_id} not found.")
        return

    print_teamevent_detail(event, teamevent_repo.list_event_vehicles(teamevent_id))


def edit_teamevent(args: list[str]) -> None:
    teamevent_id, name, tracks, max_score, vehicles_arg, ok = _parse_edit_args(args)
    if not ok:
        return

    updates: dict[str, object] = {}
    if name is not None:
        updates["name"] = name
    if tracks is not None:
        updates["tracks"] = tracks
    if max_score is not None:
        updates["max_score_per_track"] = max_score

    if updates:
        teamevent_repo.update_teamevent(teamevent_id, updates)
        print(f"✅ Team event {teamevent_id} updated.")

    if vehicles_arg is not None:
        if vehicles_arg == "-":
            teamevent_repo.clear_event_vehicles(teamevent_id)
            print(f"✅ Cleared vehicles for team event {teamevent_id}.")
        else:
            tokens = [t.strip() for t in vehicles_arg.split(",") if t.strip()]
            resolved_ids, warnings = _resolve_vehicle_inputs(tokens, allow_name_lookup=True)
            warnings.extend(str(vehicle_id) for vehicle_id in teamevent_repo.replace_event_vehicles(teamevent_id, resolved_ids))

            if resolved_ids:
                print(f"✅ Updated vehicles for team event {teamevent_id}: {','.join(map(str, resolved_ids))}")
            else:
                print(f"✅ Updated vehicles for team event {teamevent_id}: (none)")

            if warnings:
                print("⚠️  Unresolved/invalid vehicle tokens: " + ", ".join(warnings))


def delete_teamevent(teamevent_id: int) -> None:
    teamevent_repo.delete_teamevent(teamevent_id)
    print(f"🗑️  Team event {teamevent_id} deleted.")
