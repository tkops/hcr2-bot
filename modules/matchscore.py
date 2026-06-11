#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Callable, Optional

from modules.common import (
    connect_db,
    is_absent_on,
    is_help_request,
    parse_bool01,
    parse_flag_map,
    parse_int,
    parse_ymd,
    print_command_help,
    print_unknown_command,
)


USAGE_ADD = (
    "Usage: matchscore add <match_id> <player_id|name> <score> <points> [<absent01>] [<checkin01>] "
    "| --match <match_id> --player <player_id|name> --score <score> --points <points> "
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


def _parse_ymd(value):
    return parse_ymd(value)


def _is_absent_on(match_day, from_str, until_str):
    return is_absent_on(match_day, from_str, until_str)


def _compute_absent(conn, match_id, player_id):
    cur = conn.cursor()
    cur.execute("SELECT start FROM match WHERE id = ?", (match_id,))
    row = cur.fetchone()
    if not row:
        return 0
    match_day = _parse_ymd(row[0])
    cur.execute("SELECT away_from, away_until FROM players WHERE id = ?", (player_id,))
    player_row = cur.fetchone()
    if not player_row:
        return 0
    return 1 if _is_absent_on(match_day, player_row[0], player_row[1]) else 0


def _fetch_score_by_id(cur, score_id):
    cur.execute(
        """
        SELECT
            ms.id, m.id, m.start, m.opponent,
            s.name, s.division, p.name,
            ms.score, ms.points, ms.absent, ms.checkin
        FROM matchscore ms
        JOIN match   m ON ms.match_id      = m.id
        JOIN season  s ON m.season_number  = s.number
        JOIN players p ON ms.player_id     = p.id
        WHERE ms.id = ?
        """,
        (score_id,),
    )
    return cur.fetchone()


def _fetch_ms_by_unique(cur, match_id, player_id):
    cur.execute(
        "SELECT id, score, points, absent, checkin FROM matchscore WHERE match_id=? AND player_id=?",
        (match_id, player_id),
    )
    return cur.fetchone()


def _season_clause(season_filter):
    if not season_filter:
        return "", []
    if season_filter == "__CURRENT__":
        return "s.number = (SELECT MAX(number) FROM season)", []
    match = re.fullmatch(r"\s*[sS]?\s*(\d+)\s*", str(season_filter))
    if match:
        return "s.number = ?", [int(match.group(1))]
    pattern = str(season_filter).replace("*", "%")
    return "s.name LIKE ?", [pattern]


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


def _query_rows(season_filter, match_filter, force_current_when_all=False):
    base = """
        SELECT ms.id, m.id, m.start, m.opponent,
               s.name, s.division, p.name, p.id, ms.score, ms.points, ms.absent, ms.checkin
        FROM matchscore ms
        JOIN match m ON ms.match_id = m.id
        JOIN season s ON m.season_number = s.number
        JOIN players p ON ms.player_id = p.id
    """
    where = []
    values = []
    if force_current_when_all and not season_filter and not match_filter:
        where.append("s.number = (SELECT MAX(number) FROM season)")
    if season_filter:
        clause, clause_values = _season_clause(season_filter)
        if clause:
            where.append(clause)
            values.extend(clause_values)
    if match_filter:
        where.append("m.id = ?")
        values.append(match_filter)
    query = base + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY m.id DESC, ms.score DESC"
    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute(query, values)
        return cur.fetchall()


def _resolve_player_id(cur, player_input):
    player_id = parse_int(player_input, default=None)
    if player_id is not None:
        return player_id

    cur.execute(
        """
        SELECT id, name, alias FROM players
        WHERE name LIKE ? OR alias LIKE ?
        """,
        (f"%{player_input}%", f"%{player_input}%"),
    )
    matches = cur.fetchall()
    if len(matches) == 0:
        print(f"❌ No player found matching: {player_input}")
        return None
    if len(matches) > 1:
        print(f"⚠️ Multiple players found for '{player_input}':")
        for pid, name, alias in matches:
            print(f"  ID {pid}: {name} (alias: {alias})")
        return None
    return matches[0][0]


def _print_score_block(block, include_pid=False, include_result=False, short=False):
    match_id = block[0][1]
    match_date = block[0][2]
    opponent = block[0][3]
    season_name = block[0][4]

    if short:
        print(f"Match {match_id} – {opponent} | {match_date}")
        print(f"{'ID':<6} {'Player':<16} {'Score':>5} {'Pts':>3}")
        print("-" * 34)
        for row in block:
            print(f"{row[0]:<6} {row[6]:<16.16} {row[8]:>5} {row[9]:>3}")
        print()
        return

    score_ladys = 0
    score_opponent = 0
    if include_result:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT score_ladys, score_opponent FROM match WHERE id = ?", (match_id,))
            score_ladys, score_opponent = cur.fetchone() or (0, 0)

    print(f"📊 Match {match_id} – {opponent} | {match_date} | Season {season_name}")
    if include_result and (score_ladys or score_opponent):
        emoji = "🏆" if score_ladys > score_opponent else ("😢" if score_ladys < score_opponent else "🤝")
        print(f"Result: {score_ladys} : {score_opponent} {emoji}")
    print()
    if include_pid:
        print(f"{'ID':<6} {'PID':<6} {'Player':<16} {'Score':>5} {'Pts':>3}")
        print("-" * 41)
        for row in block:
            print(f"{row[0]:<6} {row[7]:<6} {row[6]:<16.16} {row[8]:>5} {row[9]:>3}")
    else:
        print(f"{'ID':<6} {'Player':<16} {'Score':>5} {'Pts':>3}")
        print("-" * 34)
        for row in block:
            print(f"{row[0]:<6} {row[6]:<16.16} {row[8]:>5} {row[9]:>3}")
    print()


def _print_grouped_rows(rows, *, show_all, match_filter, short):
    if show_all or match_filter:
        group = []
        current = None
        for row in rows:
            if current is None:
                current = row[1]
            if row[1] != current:
                _print_score_block(group, include_pid=not short, include_result=not short, short=short)
                group = []
                current = row[1]
            group.append(row)
        if group:
            _print_score_block(group, include_pid=not short, include_result=not short, short=short)
        return
    _print_score_block(rows, include_pid=not short, include_result=not short, short=short)


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
        notes=["Legacy positional aliases are still accepted for add, edit and delete."],
    )


def add_score(args):
    if args and args[0].startswith("--"):
        flags = parse_flag_map(args)
        match_id = flags.get("match")
        player = flags.get("player")
        score = flags.get("score")
        points = flags.get("points")
        if not match_id or not player or score is None or points is None:
            print(USAGE_ADD)
            return
        args = [match_id, player, score, points]
        if "absent" in flags:
            args.append(flags["absent"])
        if "checkin" in flags:
            if len(args) == 4:
                args.append("0")
            args.append(flags["checkin"])

    if len(args) not in (4, 5, 6):
        print(USAGE_ADD)
        return

    match_id = _parse_int(args[0], None)
    score = _parse_int(args[2], None)
    points = _parse_int(args[3], None)
    if match_id is None or score is None or points is None:
        print("❌ Score or points out of valid range.")
        return
    if not (0 <= score <= 75000 and 0 <= points <= 300):
        print("❌ Score or points out of valid range.")
        return

    player_input = args[1]
    absent_override = _to_bool01(args[4]) if len(args) >= 5 else None
    checkin_override = _to_bool01(args[5]) if len(args) == 6 else None

    with connect_db() as conn:
        cur = conn.cursor()
        player_id = _resolve_player_id(cur, player_input)
        if player_id is None:
            return

        absent = absent_override if absent_override is not None else _compute_absent(conn, match_id, player_id)
        checkin = checkin_override if checkin_override is not None else 0

        existing = _fetch_ms_by_unique(cur, match_id, player_id)
        if existing:
            ms_id, old_score, old_points, old_absent, old_checkin = existing
            changed = (
                old_score != score
                or old_points != points
                or (old_absent or 0) != absent
                or (old_checkin or 0) != checkin
            )
            cur.execute(
                """
                UPDATE matchscore
                SET score=?, points=?, absent=?, checkin=?
                WHERE id=?
                """,
                (score, points, absent, checkin, ms_id),
            )
            conn.commit()
            print("CHANGED" if changed else "UNCHANGED")
            return

        cur.execute(
            """
            INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (match_id, player_id, score, points, absent, checkin),
        )
        conn.commit()
        print("CHANGED")


def delete_score(score_id):
    with connect_db() as conn:
        cur = conn.cursor()
        row = _fetch_score_by_id(cur, score_id)
        if not row:
            print("⚠️ Not found.")
            return
        conn.execute("DELETE FROM matchscore WHERE id = ?", (score_id,))
        print("OK DELETED:")
        print(
            f"ID={row[0]} match={row[1]} date={row[2]} opp={row[3]} "
            f"player={row[6]} score={row[7]} points={row[8]} absent={int(row[9] or 0)} checkin={int(row[10] or 0)}"
        )


def list_scores(*args):
    show_all, season_filter, match_filter = _parse_list_args(args)
    rows = _query_rows(season_filter, match_filter, force_current_when_all=show_all)
    if not rows:
        print("⚠️ No scores found.")
        return
    if not show_all and not match_filter:
        last_mid = rows[0][1]
        rows = [row for row in rows if row[1] == last_mid]
    _print_grouped_rows(rows, show_all=show_all, match_filter=match_filter, short=False)


def list_scores_short(*args):
    show_all, season_filter, match_filter = _parse_list_args(args)
    rows = _query_rows(season_filter, match_filter, force_current_when_all=show_all)
    if not rows:
        print("⚠️ No scores found.")
        return
    if not show_all and not match_filter:
        last_mid = rows[0][1]
        rows = [row for row in rows if row[1] == last_mid]
    _print_grouped_rows(rows, show_all=show_all, match_filter=match_filter, short=True)


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
        except Exception:
            print("❌ --pid requires a numeric player_id.")
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

    if (
        new_score is None
        and new_points is None
        and new_absent is None
        and new_checkin is None
        and new_player_id is None
        and not (toggle_absent or toggle_checkin)
    ):
        print("⚠️ Nothing to update.")
        return

    with connect_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT match_id, player_id, absent, checkin FROM matchscore WHERE id = ?", (score_id,))
        base = cur.fetchone()
        if not base:
            print("⚠️ Not found.")
            return
        match_id, player_id, cur_absent, cur_checkin = base

        if toggle_absent:
            new_absent = 0 if (cur_absent or 0) else 1
        if toggle_checkin:
            new_checkin = 0 if (cur_checkin or 0) else 1

        if new_player_id is not None and new_player_id != player_id:
            cur.execute("SELECT 1 FROM players WHERE id = ?", (new_player_id,))
            if not cur.fetchone():
                print(f"❌ Player id {new_player_id} does not exist.")
                return
            cur.execute("SELECT id FROM matchscore WHERE match_id=? AND player_id=?", (match_id, new_player_id))
            clash = cur.fetchone()
            if clash and clash[0] != score_id:
                print(
                    f"❌ Cannot change player: entry already exists for match {match_id} and player {new_player_id} "
                    f"(matchscore.id={clash[0]})."
                )
                print("   Tip: delete or edit the existing entry first.")
                return

        sets = []
        values = []
        if new_score is not None:
            if not (0 <= new_score <= 75000):
                print("❌ Score out of range.")
                return
            sets.append("score=?")
            values.append(new_score)
        if new_points is not None:
            if not (0 <= new_points <= 300):
                print("❌ Points out of range.")
                return
            sets.append("points=?")
            values.append(new_points)
        if new_absent is not None:
            sets.append("absent=?")
            values.append(new_absent)
        if new_checkin is not None:
            sets.append("checkin=?")
            values.append(new_checkin)
        if new_player_id is not None and new_player_id != player_id:
            sets.append("player_id=?")
            values.append(new_player_id)

        if (new_score is not None or new_points is not None) and new_absent is None:
            computed = _compute_absent(conn, match_id, new_player_id if new_player_id is not None else player_id)
            sets.append("absent=?")
            values.append(computed)

        if not sets:
            print("⚠️ Nothing to update.")
            return

        values.append(score_id)
        cur.execute(f"UPDATE matchscore SET {', '.join(sets)} WHERE id = ?", values)
        conn.commit()

        row = _fetch_score_by_id(cur, score_id)
        if not row:
            print("OK UPDATED")
            return

        print("\nOK UPDATED:")
        print(f"Match {row[1]} – {row[3]} | {row[2]}")
        print(f"{'ID':<6} {'Player':<16} {'Score':>5} {'Pts':>3} {'Abs':>3} {'Cin':>3}")
        print("-" * 46)
        print(f"{row[0]:<6} {row[6]:<16.16} {row[7]:>5} {row[8]:>3} {int(row[9] or 0):>3} {int(row[10] or 0):>3}")
        print()


def _extract_score_id(args):
    if not args:
        return None
    if args[0] == "--id":
        return _parse_int(args[1], None) if len(args) > 1 else None
    return _parse_int(args[0], None)
