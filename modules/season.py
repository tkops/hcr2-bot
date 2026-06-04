from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from dateutil.relativedelta import relativedelta

from modules.common import connect_db, get_arg_value, parse_int, print_table_header


VALID_DIVISIONS = {"DIV1", "DIV2", "DIV3", "DIV4", "DIV5", "DIV6", "DIV7", "CC"}

USAGE_ADD = "Usage: season add <division> | <number> [division] | --number <number> [--division <division>]"
USAGE_DELETE = "Usage: season delete <number> | --number <number>"


def handle_command(cmd: str, args: list[str]) -> None:
    handlers: dict[str, Callable[[list[str]], None]] = {
        "add": _handle_add,
        "list": _handle_list,
        "delete": _handle_delete,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print(f"❌ Unknown season command: {cmd}")
        print_help()
        return
    handler(args)


def print_help() -> None:
    print("Usage: python hcr2.py season <command> [args]")
    print("\nCommands:")
    print("  list                                   Show the latest 10 seasons")
    print("  list all | --all                       Show all seasons")
    print("  list <number> | --number <number>      Show one season")
    print("  list <division> | --division <division>  Show seasons in one division")
    print("  add <division>                         Add the next season with one division")
    print("  add <number> [div] | --number <number> [--division <division>]")
    print("                                         Add or update one season")
    print("  delete <number> | --number <number>    Delete one season")


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
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM season")
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 1


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

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM season WHERE number = ?", (number,))
        exists = cur.fetchone()

        if exists:
            if division:
                conn.execute("UPDATE season SET division = ? WHERE number = ?", (division, number))
                print(f"🔁 Season {number} updated to division {division}")
            else:
                print(f"ℹ️ Season {number} already exists (no division update)")
            return

        conn.execute(
            "INSERT INTO season (number, name, start, division) VALUES (?, ?, ?, ?)",
            (number, name, start, division or ""),
        )
        print(f"✅ Season {number} ('{name}') added with start {start}")


def delete_season(args: list[str]) -> None:
    if not args:
        print(USAGE_DELETE)
        return

    number = _parse_season_number(get_arg_value(args, "--number") or args[0], USAGE_DELETE)
    if number is None:
        return

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM season WHERE number = ?", (number,))
        if not cur.fetchone():
            print(f"⚠️ Season {number} does not exist.")
            return

        conn.execute("DELETE FROM season WHERE number = ?", (number,))
        print(f"🗑️ Season {number} deleted.")


def get_start_date(number: int) -> str:
    base = datetime(2021, 5, 1)
    start = base + relativedelta(months=number - 1)
    return start.strftime("%Y-%m-%d")


def get_month_year_name(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%b %y")


def _build_list_query(args: list[str]) -> tuple[str, list[object]]:
    query = "SELECT number, name, start, division FROM season"
    params: list[object] = []
    suffix = "ORDER BY number DESC LIMIT 10"

    if not args:
        return f"{query} {suffix}", params

    flags_all = "--all" in args
    if flags_all:
        return f"{query} ORDER BY number", params

    flag_number = get_arg_value(args, "--number")
    if flag_number is not None:
        number = parse_int(flag_number)
        if number is None:
            print("Usage: season list [all|<number>|<division>|--all|--number <number>|--division <division>]")
            return "", []
        return f"{query} WHERE number = ?", [number]

    flag_division = get_arg_value(args, "--division")
    if flag_division is not None:
        division = _normalize_division(flag_division)
        if division is None:
            return "", []
        return f"{query} WHERE division = ? ORDER BY number", [division]

    token = args[0]
    if token.lower() == "all":
        return f"{query} ORDER BY number", params

    number = parse_int(token)
    if number is not None:
        return f"{query} WHERE number = ?", [number]

    division = _normalize_division(token)
    if division is None:
        return "", []

    return f"{query} WHERE division = ? ORDER BY number", [division]


def list_seasons(args: list[str]) -> None:
    query, params = _build_list_query(args)
    if not query:
        return

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()

    print_table_header(columns=[f"{'No.':3}", f"{'Name':<8}", f"{'Div':<6}"], width=25)
    for number, name, _, division in rows:
        print(f"{number:>3}.  {name:<8} {division:<6}")
