from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from dateutil.relativedelta import relativedelta

from hcr2.output.seasons import print_seasons
from hcr2.repositories import seasons as season_repo
from modules.common import (
    get_arg_value,
    is_help_request,
    parse_int,
    print_command_help,
    print_unknown_command,
)


VALID_DIVISIONS = {"DIV1", "DIV2", "DIV3", "DIV4", "DIV5", "DIV6", "DIV7", "CC"}

USAGE_ADD = "Usage: season add <division> | <number> [division] | --number <number> [--division <division>]"
USAGE_DELETE = "Usage: season delete <number> | --number <number>"


def handle_command(cmd: str, args: list[str]) -> None:
    if is_help_request(cmd, *args):
        print_help()
        return

    handlers: dict[str, Callable[[list[str]], None]] = {
        "add": _handle_add,
        "list": _handle_list,
        "delete": _handle_delete,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print_unknown_command("season", cmd)
        print_help()
        return
    handler(args)


def print_help() -> None:
    print_command_help(
        usage="hcr2.py season <command> [options]",
        commands=[
            ("list", "Show the latest 10 seasons"),
            ("list --all", "Show all seasons"),
            ("list --number <number>", "Show one season"),
            ("list --division <division>", "Show seasons in one division"),
            ("add <division>", "Add the next season with one division"),
            ("add --number <number> [--division <division>]", "Add or update one season"),
            ("delete --number <number>", "Delete one season"),
        ],
        notes=["Legacy positional aliases are still accepted for list, add and delete."],
    )


def _handle_add(args: list[str]) -> None:
    add_or_update_season(args)


def _handle_list(args: list[str]) -> None:
    list_seasons(args)


def _handle_delete(args: list[str]) -> None:
    delete_season(args)


def _normalize_division(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    division = value.upper()
    if division not in VALID_DIVISIONS:
        print("❌ Invalid division. Use CC or DIV1 to DIV7.")
        return None
    return division


def _parse_season_number(value: Optional[str], usage: str) -> Optional[int]:
    number = parse_int(value)
    if number is None:
        print(usage)
        return None
    return number


def _get_next_season_number() -> int:
    return season_repo.get_next_season_number()


def add_or_update_season(args: list[str]) -> None:
    if not args:
        print(USAGE_ADD)
        return

    division_token = get_arg_value(args, "--division")
    if division_token is None and len(args) > 1 and not args[1].startswith("--"):
        division_token = args[1]

    number_token = get_arg_value(args, "--number")
    number: Optional[int]
    if number_token is not None:
        number = _parse_season_number(number_token, USAGE_ADD)
        if number is None:
            return
    else:
        first_token = args[0]
        first_division = _normalize_division(first_token)
        if first_division is not None and len(args) == 1 and division_token is None:
            number = _get_next_season_number()
            division_token = first_division
        else:
            number = _parse_season_number(first_token, USAGE_ADD)
            if number is None:
                return

    division = _normalize_division(division_token) if division_token is not None else None
    if division_token is not None and division is None:
        return

    start = get_start_date(number)
    name = get_month_year_name(start)

    if season_repo.season_exists(number):
        if division:
            season_repo.update_division(number, division)
            print(f"🔁 Season {number} updated to division {division}")
        else:
            print(f"ℹ️ Season {number} already exists (no division update)")
        return

    season_repo.add_season(number, name, start, division or "")
    print(f"✅ Season {number} ('{name}') added with start {start}")


def delete_season(args: list[str]) -> None:
    if not args:
        print(USAGE_DELETE)
        return

    number = _parse_season_number(get_arg_value(args, "--number") or args[0], USAGE_DELETE)
    if number is None:
        return

    if not season_repo.season_exists(number):
        print(f"⚠️ Season {number} does not exist.")
        return

    season_repo.delete_season(number)
    print(f"🗑️ Season {number} deleted.")


def get_start_date(number: int) -> str:
    base = datetime(2021, 5, 1)
    start = base + relativedelta(months=number - 1)
    return start.strftime("%Y-%m-%d")


def get_month_year_name(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%b %y")


def _list_matching_seasons(args: list[str]):
    if not args:
        return season_repo.list_latest()

    flags_all = "--all" in args
    if flags_all:
        return season_repo.list_all()

    flag_number = get_arg_value(args, "--number")
    if flag_number is not None:
        number = parse_int(flag_number)
        if number is None:
            print("Usage: season list [all|<number>|<division>|--all|--number <number>|--division <division>]")
            return None
        return season_repo.list_by_number(number)

    flag_division = get_arg_value(args, "--division")
    if flag_division is not None:
        division = _normalize_division(flag_division)
        if division is None:
            return None
        return season_repo.list_by_division(division)

    token = args[0]
    if token.lower() == "all":
        return season_repo.list_all()

    number = parse_int(token)
    if number is not None:
        return season_repo.list_by_number(number)

    division = _normalize_division(token)
    if division is None:
        return None

    return season_repo.list_by_division(division)


def list_seasons(args: list[str]) -> None:
    seasons = _list_matching_seasons(args)
    if seasons is None:
        return

    print_seasons(seasons)
