#!/usr/bin/env python3
"""CLI adapter for the weekly distance chest."""
from __future__ import annotations

from typing import Callable

from hcr2.output import distances as distance_output
from hcr2.services import distances as distance_service
from hcr2.services import players as player_service
from modules.common import (
    get_arg_value,
    is_help_request,
    parse_int,
    print_command_help,
    print_error,
    print_unknown_command,
)


USAGE_ADD = "Usage: distance add --player <id|name> --km <km> [--year <yyyy>] [--week <n>]"
USAGE_DELETE = "Usage: distance delete --id <entry_id>"
USAGE_LIST = "Usage: distance list [--year <yyyy>] [--week <n>]"
USAGE_SHOW = "Usage: distance show --player <id|name> [--num <weeks>]"
USAGE_WEEKS = "Usage: distance weeks [--num <weeks>]"


def print_help():
    print_command_help(
        usage="hcr2.py distance <command> [options]",
        commands=[
            ("list [--year <yyyy>] [--week <n>]", "Kilometre ranking of one week"),
            ("show --player <id|name> [--num <weeks>]", "One player's weeks with rank and average"),
            ("weeks [--num <weeks>]", "Team totals per week"),
            ("add --player <id|name> --km <km> [--year <yyyy>] [--week <n>]", "Add or correct one week"),
            ("delete --id <entry_id>", "Delete one entry"),
        ],
        notes=[
            "Without --year/--week the most recent stored week is used.",
            "One row per player and ISO week - the value is that week's distance, not a total.",
        ],
    )


def handle_command(command, args):
    if is_help_request(command, *args):
        print_help()
        return

    handlers: dict[str, Callable[[list[str]], None]] = {
        "list": _handle_list,
        "show": _handle_show,
        "weeks": _handle_weeks,
        "add": _handle_add,
        "delete": _handle_delete,
    }
    handler = handlers.get(command)
    if handler is None:
        print_unknown_command("distance", command)
        print_help()
        return
    handler(args)


def _week_from(args):
    year = parse_int(get_arg_value(args, "year"), default=None)
    week = parse_int(get_arg_value(args, "week"), default=None)
    return distance_service.resolve_week(year, week)


def _handle_list(args):
    resolved = _week_from(args)
    if resolved is None:
        distance_output.print_invalid_week()
        return
    year, week = resolved
    distance_output.print_ranking(year, week, distance_service.ranking(year, week))


def _handle_show(args):
    player = get_arg_value(args, "player")
    if not player:
        print(USAGE_SHOW)
        return

    resolution = player_service.resolve_player_id_fuzzy(player)
    if resolution.player_id is None:
        print_error("Player not found." if not resolution.matches else "Player name is ambiguous - use the id.")
        return

    detail = player_service.get_player_detail(resolution.player_id)
    rows = distance_service.history(
        resolution.player_id, limit=parse_int(get_arg_value(args, "num"), default=12)
    )
    distance_output.print_history(detail.name if detail else str(resolution.player_id), rows)


def _handle_weeks(args):
    distance_output.print_weeks(distance_service.weeks(parse_int(get_arg_value(args, "num"), default=12)))


def _handle_add(args):
    player = get_arg_value(args, "player")
    km = parse_int(get_arg_value(args, "km"), default=None)
    if not player or km is None:
        print(USAGE_ADD)
        return

    resolved = _week_from(args)
    if resolved is None:
        distance_output.print_invalid_week()
        return

    year, week = resolved
    result = distance_service.add_distance(player_input=player, year=year, week=week, km=km)
    distance_output.print_add_result(result, year=year, week=week, km=km)


def _handle_delete(args):
    entry_id = parse_int(get_arg_value(args, "id"), default=None)
    if entry_id is None:
        print(USAGE_DELETE)
        return
    distance_output.print_delete_result(entry_id, distance_service.delete_distance(entry_id))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2 or sys.argv[1] != "distance":
        print_help()
    else:
        handle_command(sys.argv[2] if len(sys.argv) > 2 else "", sys.argv[3:])
