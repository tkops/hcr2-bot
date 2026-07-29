from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

from dateutil.relativedelta import relativedelta

from hcr2.output.matches import print_match_detail, print_match_list
from hcr2.repositories import matches as match_repo
from modules.common import (
    get_arg_value,
    is_help_request,
    parse_flag_map,
    parse_int,
    print_command_help,
    print_unknown_command,
)


USAGE_ADD = (
    "Usage: match add <opponent> [--teamevent ID] [--season NUM] "
    "[--start YYYY-MM-DD] [--score N] [--scoreopp N]\n"
    "   or: match add --opponent NAME [--teamevent ID] [--season NUM] "
    "[--start YYYY-MM-DD] [--score N] [--scoreopp N]"
)
USAGE_EDIT = (
    "Usage: match edit --id ID [--teamevent ID] [--season NUM] [--start YYYY-MM-DD] "
    "[--opponent NAME] [--score N] [--scoreopp N]"
)
USAGE_SHOW = "Usage: match show <id> | --id <id>"
USAGE_DELETE = "Usage: match delete <id> | --id <id>"


def handle_command(cmd: str, args: list[str]) -> None:
    if is_help_request(cmd, *args):
        print_help()
        return

    handlers: dict[str, Callable[[list[str]], None]] = {
        "add": _handle_add,
        "list": _handle_list,
        "edit": _handle_edit,
        "show": _handle_show,
        "delete": _handle_delete,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print_unknown_command("match", cmd)
        print_help()
        return
    handler(args)


def print_help() -> None:
    print_command_help(
        usage="hcr2.py match <command> [options]",
        commands=[
            ("add <opponent> [--teamevent ID] [--season NUM] [--start YYYY-MM-DD] [--score N] [--scoreopp N]", "Add one match"),
            ("edit --id ID [--teamevent ID] [--season NUM] [--start YYYY-MM-DD] [--opponent NAME] [--score N] [--scoreopp N]", "Edit one match"),
            ("show --id <id>", "Show one match"),
            ("list [--season <n>|--all]", "List matches"),
            ("delete --id <id>", "Delete one match"),
        ],
        notes=[
            "For add, the opponent can be positional or passed with --opponent.",
            "Default --teamevent is the latest team event by ISO year/week.",
            "Default --season is the current season.",
            "Default --start is the last match date + 2 days, or the first day of the current month.",
            "Legacy positional aliases are still accepted for list, show and delete.",
        ],
    )


def _handle_add(args: list[str]) -> None:
    add_match(args)


def _handle_list(args: list[str]) -> None:
    if "--all" in args or (args and args[0] == "all"):
        list_matches(all_seasons=True)
        return
    season_flag = get_arg_value(args, "--season")
    if season_flag is not None:
        season_number = parse_int(season_flag)
        if season_number is None:
            print("Usage: match list [season_number|all|--season <n>|--all]")
            return
        list_matches(season_number=season_number)
        return
    if args:
        season_number = parse_int(args[0])
        if season_number is None:
            print("Usage: match list [season_number|all|--season <n>|--all]")
            return
        list_matches(season_number=season_number)
        return
    list_matches()


def _handle_edit(args: list[str]) -> None:
    edit_match(args)


def _handle_show(args: list[str]) -> None:
    match_id = _extract_match_id(args)
    if match_id is None:
        print(USAGE_SHOW)
        return
    show_match(match_id)


def _handle_delete(args: list[str]) -> None:
    match_id = _extract_match_id(args)
    if match_id is None:
        print(USAGE_DELETE)
        return
    delete_match(match_id)


def _extract_match_id(args: list[str]) -> Optional[int]:
    if not args:
        return None
    if args[0] == "--id":
        return parse_int(args[1]) if len(args) > 1 else None
    return parse_int(args[0])


def _parse_flags(args: list[str]) -> dict[str, str]:
    return parse_flag_map(args)


def _positional_values(args: list[str]) -> list[str]:
    values: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if not token.startswith("--"):
            values.append(token)
            i += 1
            continue

        if "=" in token:
            i += 1
            continue

        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            i += 2
            continue

        i += 1
    return values


def _require_int(flags: dict[str, str], key: str) -> Optional[int]:
    value = parse_int(flags.get(key))
    if value is None:
        print(f"❌ Invalid integer for '{key}': {flags.get(key)!r}")
    return value


def _teamevent_exists(cur, teamevent_id: int) -> bool:
    return match_repo.teamevent_exists(teamevent_id)


def _get_latest_teamevent_id(cur) -> Optional[int]:
    return match_repo.latest_teamevent_id()


def _get_default_start(cur) -> str:
    today = datetime.today()
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    month_end = (today.replace(day=1) + relativedelta(months=1)).strftime("%Y-%m-%d")

    latest_start = match_repo.latest_match_start_between(month_start, month_end)
    if latest_start is None:
        return month_start

    last_start = datetime.strptime(latest_start, "%Y-%m-%d")
    return (last_start + timedelta(days=2)).strftime("%Y-%m-%d")


def add_match(args: list[str]) -> None:
    flags = _parse_flags(args)

    opponent = flags.get("opponent") or " ".join(_positional_values(args)).strip()
    if not opponent:
        print(USAGE_ADD)
        print("Missing: opponent")
        return

    score_ladys = parse_int(flags.get("score", "0"))
    score_opponent = parse_int(flags.get("scoreopp", "0"))
    if score_ladys is None:
        print(f"❌ Invalid integer for 'score': {flags.get('score', '0')!r}")
        return
    if score_opponent is None:
        print(f"❌ Invalid integer for 'scoreopp': {flags.get('scoreopp', '0')!r}")
        return

    if "teamevent" in flags:
        teamevent_id = _require_int(flags, "teamevent")
        if teamevent_id is None:
            return
        if not match_repo.teamevent_exists(teamevent_id):
            print(f"❌ Team event ID {teamevent_id} not found.")
            return
    else:
        teamevent_id = match_repo.latest_teamevent_id()
        if teamevent_id is None:
            print("❌ No team event found.")
            return

    if "season" in flags:
        season_number = _require_int(flags, "season")
        if season_number is None:
            return
    else:
        season_number = get_current_season_number()

    start = flags.get("start") if "start" in flags else _get_default_start(None)

    match_repo.add_match(
        teamevent_id=teamevent_id,
        season_number=season_number,
        start=start,
        opponent=opponent,
        score_ladys=score_ladys,
        score_opponent=score_opponent,
    )

    print(f"✅ Match added: Event {teamevent_id}, Season {season_number}, vs {opponent} on {start} "
          f"(Score Ladies: {score_ladys}, Score Opponent: {score_opponent})")


def edit_match(args: list[str]) -> None:
    flags = _parse_flags(args)

    match_id = _require_int(flags, "id")
    if match_id is None:
        print(USAGE_EDIT)
        return

    updates: dict[str, object] = {}

    if "teamevent" in flags:
        teamevent_id = _require_int(flags, "teamevent")
        if teamevent_id is None:
            return
        if not match_repo.teamevent_exists(teamevent_id):
            print(f"❌ Team event ID {teamevent_id} not found.")
            return
        updates["teamevent_id"] = teamevent_id

    if "season" in flags:
        season_number = _require_int(flags, "season")
        if season_number is None:
            return
        updates["season_number"] = season_number

    if "start" in flags:
        updates["start"] = flags.get("start")

    if "opponent" in flags:
        updates["opponent"] = flags.get("opponent")

    if "score" in flags:
        score_ladys = _require_int(flags, "score")
        if score_ladys is None:
            return
        updates["score_ladys"] = score_ladys

    if "scoreopp" in flags:
        score_opponent = _require_int(flags, "scoreopp")
        if score_opponent is None:
            return
        updates["score_opponent"] = score_opponent

    if not updates:
        print("Nothing to update. Provide at least one of: "
              "--teamevent / --season / --start / --opponent / --score / --scoreopp")
        return

    if match_repo.update_match(match_id, updates) == 0:
        print(f"❌ Match ID {match_id} not found.")
        return

    print(f"✏️  Match {match_id} updated.")


def get_current_season_number() -> int:
    base = datetime(2021, 5, 1)
    today = datetime.today()
    delta = relativedelta(today, base)
    return delta.years * 12 + delta.months + 1


def list_matches(season_number: Optional[int] = None, all_seasons: bool = False) -> None:
    if not all_seasons and season_number is None:
        season_number = get_current_season_number()
    matches = match_repo.list_matches(season_number=season_number, all_seasons=all_seasons)
    print_match_list(matches, season_number=season_number, all_seasons=all_seasons)


def show_match(match_id: int) -> None:
    match = match_repo.get_match(match_id)
    if match is None:
        print(f"❌ Match ID {match_id} not found.")
        return

    print_match_detail(match)


def warn_if_unusual_match_count(season_number: int, actual_count: int) -> None:
    start = datetime(2021, 5, 1) + relativedelta(months=season_number - 1)
    month = start.month

    if month == 2:
        expected = 13
    elif month in [4, 6, 9, 11]:
        expected = 14
    else:
        expected = 15

    if actual_count != expected:
        print(f"⚠️  Warning: Expected {expected} matches for {start.strftime('%B %Y')} "
              f"(Season {season_number}), but found {actual_count}.")


def delete_match(match_id: int) -> None:
    match_repo.delete_match(match_id)
    print(f"🗑️  Match {match_id} deleted.")
