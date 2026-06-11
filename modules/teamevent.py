from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Callable, Optional

from modules.common import (
    connect_db,
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
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT iso_year, iso_week
            FROM teamevent
            ORDER BY iso_year DESC, iso_week DESC, id DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()

    if not row:
        next_week = date.today() + timedelta(days=7)
        iso_year, iso_week, _ = next_week.isocalendar()
        return iso_year, iso_week

    latest_year, latest_week = int(row[0]), int(row[1])
    next_monday = date.fromisocalendar(latest_year, latest_week, 1) + timedelta(days=7)
    iso_year, iso_week, _ = next_monday.isocalendar()
    return iso_year, iso_week


def _resolve_vehicle_id(cur: sqlite3.Cursor, token: str) -> Optional[int]:
    if token.isdigit():
        return int(token)

    cur.execute(
        """
        SELECT id
        FROM vehicle
        WHERE LOWER(shortname) = LOWER(?)
           OR LOWER(name) = LOWER(?)
        ORDER BY id
        LIMIT 1
        """,
        (token, token),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _resolve_vehicle_inputs(
    cur: sqlite3.Cursor,
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
            if allow_name_lookup:
                vehicle_id = _resolve_vehicle_id(cur, token)
            else:
                cur.execute("SELECT id FROM vehicle WHERE shortname = ?", (token,))
                row = cur.fetchone()
                vehicle_id = row[0] if row else None

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

    with connect_db() as conn:
        cur = conn.cursor()
        resolved_ids, warnings = _resolve_vehicle_inputs(cur, vehicle_inputs, allow_name_lookup=False)

        for token in warnings:
            print(f"⚠️  Vehicle '{token}' not found (neither ID nor shortname).")

        try:
            cur.execute(
                """
                INSERT INTO teamevent (name, iso_year, iso_week, tracks, max_score_per_track)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, iso_year, iso_week, tracks, max_score),
            )
            teamevent_id = cur.lastrowid

            for vehicle_id in resolved_ids:
                try:
                    cur.execute(
                        "INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (?, ?)",
                        (teamevent_id, vehicle_id),
                    )
                except sqlite3.IntegrityError:
                    print(f"⚠️  Vehicle ID {vehicle_id} does not exist or is already linked.")

            conn.commit()
            print("✅ Team event added:")
            show_teamevent([str(teamevent_id)])
        except sqlite3.IntegrityError:
            print(f"❌ Team event for week {iso_week}/{iso_year} already exists.")


def list_teamevents() -> None:
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, iso_year, iso_week
            FROM teamevent ORDER BY iso_year DESC, iso_week DESC LIMIT 10
            """
        )
        events = cur.fetchall()

    print(f"{'ID.':>4} {'Year':<6} {'Wk':<4}  {'Name'}")
    print("-" * 40)
    for teamevent_id, name, iso_year, iso_week in events:
        print(f"{teamevent_id:>3}. {iso_year:<6} {iso_week:<4}  {name}")


def show_teamevent(args: list[str]) -> None:
    if not args:
        print(USAGE_SHOW)
        return

    if args[0] == "all" or args == ["--all"]:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, name, iso_year, iso_week, tracks, max_score_per_track
                FROM teamevent ORDER BY iso_year DESC, iso_week DESC
                """
            )
            events = cur.fetchall()

        print(f"{'ID.':>4} {'Year':<6} {'Wk':<4}  {'Name':<25}  {'Tracks':<6}  {'Score/Track':<12}")
        print("-" * 70)
        for teamevent_id, name, year, week, tracks, score in events:
            print(f"{teamevent_id:>3}. {year:<6} {week:<4}  {name:<25}  {tracks:<6}  {score:<12}")
        return

    teamevent_id = _extract_teamevent_id(args)
    if teamevent_id is None:
        print(USAGE_SHOW)
        return

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, iso_year, iso_week, tracks, max_score_per_track
            FROM teamevent WHERE id = ?
            """,
            (teamevent_id,),
        )
        row = cur.fetchone()
        if not row:
            print(f"❌ Team event {teamevent_id} not found.")
            return

        te_id, name, year, week, tracks, score = row
        cur.execute(
            """
            SELECT v.id, v.name
            FROM teamevent_vehicle tv
            JOIN vehicle v ON tv.vehicle_id = v.id
            WHERE tv.teamevent_id = ?
            ORDER BY v.id
            """,
            (te_id,),
        )
        vehicles = cur.fetchall()

    print(f"\nTeam event {te_id}:")
    print(f"  Name         : {name}")
    print(f"  Year/Wk      : {year}/W{week}")
    print(f"  Tracks       : {tracks}")
    print(f"  Score/Track  : {score}")
    print(f"  Vehicles     :")
    if vehicles:
        for vehicle_id, vehicle_name in vehicles:
            print(f"    - {vehicle_id}: {vehicle_name}")
    else:
        print("    (none)")


def edit_teamevent(args: list[str]) -> None:
    teamevent_id, name, tracks, max_score, vehicles_arg, ok = _parse_edit_args(args)
    if not ok:
        return

    fields = []
    values = []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if tracks is not None:
        fields.append("tracks = ?")
        values.append(tracks)
    if max_score is not None:
        fields.append("max_score_per_track = ?")
        values.append(max_score)

    with connect_db() as conn:
        cur = conn.cursor()

        if fields:
            values.append(teamevent_id)
            query = f"UPDATE teamevent SET {', '.join(fields)} WHERE id = ?"
            cur.execute(query, values)
            print(f"✅ Team event {teamevent_id} updated.")

        if vehicles_arg is not None:
            if vehicles_arg == "-":
                cur.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (teamevent_id,))
                print(f"✅ Cleared vehicles for team event {teamevent_id}.")
            else:
                tokens = [t.strip() for t in vehicles_arg.split(",") if t.strip()]
                resolved_ids, warnings = _resolve_vehicle_inputs(cur, tokens, allow_name_lookup=True)

                cur.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (teamevent_id,))
                for vehicle_id in resolved_ids:
                    try:
                        cur.execute(
                            "INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (?, ?)",
                            (teamevent_id, vehicle_id),
                        )
                    except sqlite3.IntegrityError:
                        warnings.append(str(vehicle_id))

                if resolved_ids:
                    print(f"✅ Updated vehicles for team event {teamevent_id}: {','.join(map(str, resolved_ids))}")
                else:
                    print(f"✅ Updated vehicles for team event {teamevent_id}: (none)")

                if warnings:
                    print("⚠️  Unresolved/invalid vehicle tokens: " + ", ".join(warnings))


def delete_teamevent(teamevent_id: int) -> None:
    with connect_db() as conn:
        conn.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (teamevent_id,))
        conn.execute("DELETE FROM teamevent WHERE id = ?", (teamevent_id,))
    print(f"🗑️  Team event {teamevent_id} deleted.")
