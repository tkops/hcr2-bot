#!/usr/bin/env python3
from __future__ import annotations

from typing import Callable

from hcr2.output import matchscores as matchscore_output
from hcr2.repositories import matchscores as matchscore_repo
from hcr2.services import matchscores as matchscore_service
from modules.common import (
    is_help_request,
    parse_bool01,
    parse_flag_map,
    parse_int,
    print_command_help,
    print_unknown_command,
)


USAGE_ADD = (
    "Usage: matchscore add --match <match_id> --player <player_id|name> --score <score> --points <points> "
    "[--absent true|false|1|0] [--checkin true|false|1|0]"
)
USAGE_DELETE = "Usage: matchscore delete <id> | --id <id>"
USAGE_EDIT = (
    "Usage: matchscore edit <id> [--score <0..75000>] [--points <0..300>] "
    "| --id <id> [--score <0..75000>] [--points <0..300>] "
    "[--pid <player_id>] [--absent true|false|toggle] [--checkin true|false|toggle]"
)


def _to_bool01(value):
    return parse_bool01(value, default=0)


def _parse_int(value, default=0):
    return parse_int(value, default=default)


def _parse_list_args(args):
    show_all = False
    season_filter = None
    match_filter = None
    if "--all" in args:
        show_all = True
    flags = parse_flag_map(args)
    if "match" in flags:
        match_filter = _parse_int(flags.get("match"))
    if "--season" in args:
        season_filter = flags.get("season", "__CURRENT__")
    return show_all, season_filter, match_filter


def handle_command(cmd, args):
    if is_help_request(cmd, *args):
        print_help()
        return

    handlers: dict[str, Callable[[list[str]], None]] = {
        "add": add_score,
        "list": lambda values: list_scores(*values),
        "list-short": lambda values: list_scores_short(*values),
        "delete": _handle_delete,
        "edit": edit_score,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print_unknown_command("matchscore", cmd)
        print_help()
        return
    handler(args)


def _handle_delete(args):
    score_id = _extract_score_id(args)
    if score_id is None:
        print(USAGE_DELETE)
        return
    delete_score(score_id)


def print_help():
    print_command_help(
        usage="hcr2.py matchscore <command> [options]",
        commands=[
            ("add --match <id> --player <id|name> --score <score> --points <points> [--absent true|false|1|0] [--checkin true|false|1|0]", "Add one match score"),
            ("list [--all] [--match <id>] [--season [<name_or_pattern>|<number>|S<number>]]", "Show detailed match scores"),
            ("list-short [--all] [--match <id>] [--season [<name_or_pattern>|<number>|S<number>]]", "Show compact match scores"),
            ("delete --id <id>", "Delete one match score"),
            ("edit --id <id> [--score <0..75000>] [--points <0..300>] [--pid <player_id>] [--absent true|false|toggle] [--checkin true|false|toggle]", "Edit one match score"),
        ],
        notes=["Legacy positional aliases are still accepted for edit and delete."],
    )


def add_score(args):
    flags = parse_flag_map(args)
    match_id = flags.get("match")
    player_input = flags.get("player")
    score_token = flags.get("score")
    points_token = flags.get("points")
    if not match_id or not player_input or score_token is None or points_token is None:
        print(USAGE_ADD)
        return

    score = _parse_int(score_token, None)
    points = _parse_int(points_token, None)
    match_id_int = _parse_int(match_id, None)
    if match_id_int is None or score is None or points is None:
        matchscore_output.print_invalid_score_or_points()
        return
    if not (0 <= score <= 75000 and 0 <= points <= 300):
        matchscore_output.print_invalid_score_or_points()
        return

    absent_override = _to_bool01(flags["absent"]) if "absent" in flags else None
    checkin_override = _to_bool01(flags["checkin"]) if "checkin" in flags else None

    result = matchscore_service.add_score(
        match_id=match_id_int,
        player_input=player_input,
        score=score,
        points=points,
        absent_override=absent_override,
        checkin_override=checkin_override,
    )
    matchscore_output.print_add_result(result, player_input)


def delete_score(score_id):
    result = matchscore_service.delete_score(score_id)
    matchscore_output.print_delete_result(result)


def list_scores(*args):
    show_all, season_filter, match_filter = _parse_list_args(args)
    rows = matchscore_service.list_scores(
        show_all=show_all,
        season_filter=season_filter,
        match_filter=match_filter,
    ).rows
    if not rows:
        matchscore_output.print_no_scores_found()
        return
    matchscore_output.print_grouped_rows(
        rows,
        show_all=show_all,
        match_filter=match_filter,
        short=False,
        match_result_loader=matchscore_repo.get_match_result,
    )


def list_scores_short(*args):
    show_all, season_filter, match_filter = _parse_list_args(args)
    rows = matchscore_service.list_scores(
        show_all=show_all,
        season_filter=season_filter,
        match_filter=match_filter,
    ).rows
    if not rows:
        matchscore_output.print_no_scores_found()
        return
    matchscore_output.print_grouped_rows(
        rows,
        show_all=show_all,
        match_filter=match_filter,
        short=True,
        match_result_loader=matchscore_repo.get_match_result,
    )


def edit_score(args):
    score_id = _extract_score_id(args)
    if score_id is None:
        print(USAGE_EDIT)
        return

    flag_args = args[2:] if args and args[0] == "--id" else args[1:]
    new_score = None
    new_points = None
    new_absent = None
    new_checkin = None
    new_player_id = None
    toggle_absent = False
    toggle_checkin = False

    flags = parse_flag_map(flag_args)
    if "score" in flags:
        new_score = _parse_int(flags.get("score"), None)
    if "points" in flags:
        new_points = _parse_int(flags.get("points"), None)
    if "pid" in flags:
        pid_raw = flags.get("pid")
        try:
            new_player_id = int(pid_raw)
        except (TypeError, ValueError):
            matchscore_output.print_pid_requires_numeric()
            return
    if "absent" in flags:
        value = flags.get("absent", "").strip().lower()
        if value == "toggle":
            toggle_absent = True
        else:
            new_absent = _to_bool01(value)
    if "checkin" in flags:
        value = flags.get("checkin", "").strip().lower()
        if value == "toggle":
            toggle_checkin = True
        else:
            new_checkin = _to_bool01(value)

    result = matchscore_service.edit_score(
        score_id,
        score=new_score,
        points=new_points,
        absent=new_absent,
        checkin=new_checkin,
        player_id=new_player_id,
        toggle_absent=toggle_absent,
        toggle_checkin=toggle_checkin,
    )

    matchscore_output.print_edit_result(result)


def _extract_score_id(args):
    if not args:
        return None
    if args[0] == "--id":
        return _parse_int(args[1], None) if len(args) > 1 else None
    return _parse_int(args[0], None)
