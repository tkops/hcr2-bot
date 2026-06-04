from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

from dateutil.relativedelta import relativedelta

from modules.common import connect_db, get_arg_value, parse_flag_map, parse_int, print_table_header


USAGE_ADD = (
    "Usage: match add --opponent NAME [--teamevent ID] [--season NUM] "
    "[--start YYYY-MM-DD] [--score N] [--scoreopp N]"
)
USAGE_EDIT = (
    "Usage: match edit --id ID [--teamevent ID] [--season NUM] [--start YYYY-MM-DD] "
    "[--opponent NAME] [--score N] [--scoreopp N]"
)
USAGE_SHOW = "Usage: match show <id> | --id <id>"
USAGE_DELETE = "Usage: match delete <id> | --id <id>"


def handle_command(cmd: str, args: list[str]) -> None:
    handlers: dict[str, Callable[[list[str]], None]] = {
        "add": _handle_add,
        "list": _handle_list,
        "edit": _handle_edit,
        "show": _handle_show,
        "delete": _handle_delete,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print(f"❌ Unknown match command: {cmd}")
        print_help()
        return
    handler(args)


def print_help() -> None:
    print("Usage: python hcr2.py match <command> [args]")
    print("\nCommands:")
    print("  add --opponent NAME [--teamevent ID] [--season NUM] [--start YYYY-MM-DD] [--score N] [--scoreopp N]")
    print("                                      Add one match")
    print("  edit --id ID [--teamevent ID] [--season NUM] [--start YYYY-MM-DD]")
    print("       [--opponent NAME] [--score N] [--scoreopp N]")
    print("                                      Edit one match")
    print("  show <id> | --id <id>                Show one match")
    print("  list [season_number|all|--season <n>|--all]")
    print("                                      List matches")
    print("  delete <id> | --id <id>              Delete one match")
    print("\nDefaults for add:")
    print("  • --teamevent: latest teamevent by ISO year/week")
    print("  • --season:    current season")
    print("  • --start:     last match date + 2 days")
    print("                 or first day of current month if no match exists in current month")
    print("  • required:    --opponent only")


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


def _require_int(flags: dict[str, str], key: str) -> Optional[int]:
    value = parse_int(flags.get(key))
    if value is None:
        print(f"❌ Invalid integer for '{key}': {flags.get(key)!r}")
    return value


def _teamevent_exists(cur, teamevent_id: int) -> bool:
    cur.execute("SELECT 1 FROM teamevent WHERE id = ? LIMIT 1", (teamevent_id,))
    return cur.fetchone() is not None


def _get_latest_teamevent_id(cur) -> Optional[int]:
    cur.execute(
        """
        SELECT id
        FROM teamevent
        ORDER BY iso_year DESC, iso_week DESC, id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    return row[0] if row else None


def _get_default_start(cur) -> str:
    today = datetime.today()
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    month_end = (today.replace(day=1) + relativedelta(months=1)).strftime("%Y-%m-%d")

    cur.execute(
        """
        SELECT start
        FROM match
        WHERE start >= ? AND start < ?
        ORDER BY start DESC, id DESC
        LIMIT 1
        """,
        (month_start, month_end),
    )
    row = cur.fetchone()
    if not row:
        return month_start

    last_start = datetime.strptime(row[0], "%Y-%m-%d")
    return (last_start + timedelta(days=2)).strftime("%Y-%m-%d")


def add_match(args: list[str]) -> None:
    flags = _parse_flags(args)

    opponent = flags.get("opponent")
    if not opponent:
        print(USAGE_ADD)
        print("Missing: --opponent")
        return

    score_ladys = parse_int(flags.get("score", "0"))
    score_opponent = parse_int(flags.get("scoreopp", "0"))
    if score_ladys is None:
        print(f"❌ Invalid integer for 'score': {flags.get('score', '0')!r}")
        return
    if score_opponent is None:
        print(f"❌ Invalid integer for 'scoreopp': {flags.get('scoreopp', '0')!r}")
        return

    with connect_db() as conn:
        cur = conn.cursor()

        if "teamevent" in flags:
            teamevent_id = _require_int(flags, "teamevent")
            if teamevent_id is None:
                return
            if not _teamevent_exists(cur, teamevent_id):
                print(f"❌ Team event ID {teamevent_id} not found.")
                return
        else:
            teamevent_id = _get_latest_teamevent_id(cur)
            if teamevent_id is None:
                print("❌ No team event found.")
                return

        if "season" in flags:
            season_number = _require_int(flags, "season")
            if season_number is None:
                return
        else:
            season_number = get_current_season_number()

        start = flags.get("start") if "start" in flags else _get_default_start(cur)

        cur.execute(
            """
            INSERT INTO match (teamevent_id, season_number, start, opponent, score_ladys, score_opponent)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (teamevent_id, season_number, start, opponent, score_ladys, score_opponent),
        )

    print(f"✅ Match added: Event {teamevent_id}, Season {season_number}, vs {opponent} on {start} "
          f"(Score Ladies: {score_ladys}, Score Opponent: {score_opponent})")


def edit_match(args: list[str]) -> None:
    flags = _parse_flags(args)

    match_id = _require_int(flags, "id")
    if match_id is None:
        print(USAGE_EDIT)
        return

    set_clauses: list[str] = []
    values: list[object] = []

    with connect_db() as conn:
        cur = conn.cursor()

        if "teamevent" in flags:
            teamevent_id = _require_int(flags, "teamevent")
            if teamevent_id is None:
                return
            if not _teamevent_exists(cur, teamevent_id):
                print(f"❌ Team event ID {teamevent_id} not found.")
                return
            set_clauses.append("teamevent_id = ?")
            values.append(teamevent_id)

        if "season" in flags:
            season_number = _require_int(flags, "season")
            if season_number is None:
                return
            set_clauses.append("season_number = ?")
            values.append(season_number)

        if "start" in flags:
            set_clauses.append("start = ?")
            values.append(flags.get("start"))

        if "opponent" in flags:
            set_clauses.append("opponent = ?")
            values.append(flags.get("opponent"))

        if "score" in flags:
            score_ladys = _require_int(flags, "score")
            if score_ladys is None:
                return
            set_clauses.append("score_ladys = ?")
            values.append(score_ladys)

        if "scoreopp" in flags:
            score_opponent = _require_int(flags, "scoreopp")
            if score_opponent is None:
                return
            set_clauses.append("score_opponent = ?")
            values.append(score_opponent)

        if not set_clauses:
            print("Nothing to update. Provide at least one of: "
                  "--teamevent / --season / --start / --opponent / --score / --scoreopp")
            return

        cur.execute(f"UPDATE match SET {', '.join(set_clauses)} WHERE id = ?", (*values, match_id))
        if cur.rowcount == 0:
            print(f"❌ Match ID {match_id} not found.")
            return

    print(f"✏️  Match {match_id} updated.")


def get_current_season_number() -> int:
    base = datetime(2021, 5, 1)
    today = datetime.today()
    delta = relativedelta(today, base)
    return delta.years * 12 + delta.months + 1


def list_matches(season_number: Optional[int] = None, all_seasons: bool = False) -> None:
    with connect_db() as conn:
        cur = conn.cursor()
        if all_seasons:
            cur.execute(
                """
                SELECT m.id, m.start, t.name, m.opponent
                FROM match m
                JOIN teamevent t ON m.teamevent_id = t.id
                ORDER BY m.start DESC
                """
            )
            matches = cur.fetchall()
        else:
            if season_number is None:
                season_number = get_current_season_number()
            cur.execute(
                """
                SELECT m.id, m.start, t.name, m.opponent
                FROM match m
                JOIN teamevent t ON m.teamevent_id = t.id
                WHERE m.season_number = ?
                ORDER BY m.start DESC
                """,
                (season_number,),
            )
            matches = cur.fetchall()

    print_table_header(
        columns=[f"{'ID':<5}", f"{'Start':<12}", f"{'Event':<30}", f"{'Opponent':<20}"],
        width=75,
    )
    for match_id, start, event_name, opponent in matches:
        print(f"{match_id:<5} {start:<12} {event_name:<30} {opponent:<20}")

    if not all_seasons:
        print(f"\n📊 {len(matches)} matches in Season {season_number}")


def show_match(match_id: int) -> None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.id, m.start, m.season_number, m.opponent, t.name, m.score_ladys, m.score_opponent
            FROM match m
            JOIN teamevent t ON m.teamevent_id = t.id
            WHERE m.id = ?
            """,
            (match_id,),
        )
        row = cur.fetchone()

    if not row:
        print(f"❌ Match ID {match_id} not found.")
        return

    mid, start, season_number, opponent, event_name, score_ladys, score_opponent = row
    print(f"📅 Match {mid}")
    print(f"  Start:       {start}")
    print(f"  Season:      {season_number}")
    print(f"  Event:       {event_name}")
    print(f"  Opponent:    {opponent}")
    print(f"  Score Ladies: {score_ladys}")
    print(f"  Score Opp.:  {score_opponent}")


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
    with connect_db() as conn:
        conn.execute("DELETE FROM match WHERE id = ?", (match_id,))
    print(f"🗑️  Match {match_id} deleted.")
