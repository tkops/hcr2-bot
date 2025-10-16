# matchscore.py
#!/usr/bin/env python3
import sqlite3
from datetime import datetime
import re

DB_PATH = "../hcr2-db/hcr2.db"

# ===================== Helpers =====================

def _to_bool01(x):
    if x is None:
        return 0
    s = str(x).strip().lower()
    if s in ("1", "true", "yes", "y", "ja"):
        return 1
    if s in ("0", "false", "no", "n", "nein", ""):
        return 0
    try:
        return 1 if int(s) != 0 else 0
    except Exception:
        return 0

def _parse_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

def _parse_ymd(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _is_absent_on(match_day, from_str, until_str):
    frm = _parse_ymd(from_str) if from_str else None
    until = _parse_ymd(until_str) if until_str else None
    if frm and until:
        return frm <= match_day <= until
    if frm and not until:
        return match_day >= frm
    if until and not frm:
        return match_day <= until
    return False

def _compute_absent(conn, match_id, player_id):
    cur = conn.cursor()
    cur.execute("SELECT start FROM match WHERE id = ?", (match_id,))
    row = cur.fetchone()
    if not row:
        return 0
    match_day = _parse_ymd(row[0])
    cur.execute("SELECT away_from, away_until FROM players WHERE id = ?", (player_id,))
    prow = cur.fetchone()
    if not prow:
        return 0
    return 1 if _is_absent_on(match_day, prow[0], prow[1]) else 0

def _fetch_score_by_id(cur, score_id):
    cur.execute("""
        SELECT
            ms.id, m.id, m.start, m.opponent,
            s.name, s.division, p.name,
            ms.score, ms.points, ms.absent, ms.checkin
        FROM matchscore ms
        JOIN match   m ON ms.match_id      = m.id
        JOIN season  s ON m.season_number  = s.number
        JOIN players p ON ms.player_id     = p.id
        WHERE ms.id = ?
    """, (score_id,))
    return cur.fetchone()

def _fetch_ms_by_unique(cur, match_id, player_id):
    cur.execute("SELECT id, score, points, absent, checkin FROM matchscore WHERE match_id=? AND player_id=?",
                (match_id, player_id))
    return cur.fetchone()

def _season_clause(season_filter):
    if not season_filter:
        return "", []
    if season_filter == "__CURRENT__":
        return "s.number = (SELECT MAX(number) FROM season)", []
    m = re.fullmatch(r"\s*[sS]?\s*(\d+)\s*", str(season_filter))
    if m:
        return "s.number = ?", [int(m.group(1))]
    pat = str(season_filter).replace("*", "%")
    return "s.name LIKE ?", [pat]

def _parse_list_args(args):
    show_all = False
    season_filter = None
    match_filter = None
    i = 0
    while i < len(args):
        if args[i] == "--all":
            show_all = True; i += 1
        elif args[i] == "--match" and i + 1 < len(args):
            match_filter = _parse_int(args[i + 1]); i += 2
        elif args[i] == "--season":
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                season_filter = args[i + 1]; i += 2
            else:
                season_filter = "__CURRENT__"; i += 1
        else:
            i += 1
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
    where, vals = [], []
    if force_current_when_all and not season_filter and not match_filter:
        where.append("s.number = (SELECT MAX(number) FROM season)")
    if season_filter:
        clause, p = _season_clause(season_filter)
        if clause:
            where.append(clause); vals.extend(p)
    if match_filter:
        where.append("m.id = ?"); vals.append(match_filter)
    query = base + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY m.id DESC, ms.score DESC"
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(query, vals)
        return cur.fetchall()

# ===================== CLI =====================

def handle_command(cmd, args):
    if cmd == "add":
        add_score(args)
    elif cmd == "list":
        list_scores(*args)
    elif cmd == "list-short":
        list_scores_short(*args)
    elif cmd == "delete":
        if len(args) != 1:
            print("Usage: matchscore delete <id>")
            return
        delete_score(_parse_int(args[0]))
    elif cmd == "edit":
        edit_score(args)
    else:
        print(f"❌ Unknown matchscore command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py matchscore <command> [args]")
    print("\nCommands:")
    print("  add <match_id> <player_id|name> <score> <points> [<absent01>] [<checkin01>]")
    print("  list [--all] [--match <id>] [--season [<name_or_pattern>|<number>|S<number>]]")
    print("  list-short [--all] [--match <id>] [--season [<name_or_pattern>|<number>|S<number>]]")
    print("  delete <id>")
    print("  edit <id> [--score <0..75000>] [--points <0..300>] "
          "[--absent true|false|toggle] [--checkin true|false|toggle]")

# ===================== Commands =====================

def add_score(args):
    if len(args) not in (4, 5, 6):
        print("Usage: matchscore add <match_id> <player_id|name> <score> <points> [<absent01>] [<checkin01>]")
        return
    match_id  = _parse_int(args[0])
    player_in = args[1]
    score     = _parse_int(args[2])
    points    = _parse_int(args[3])
    if not (0 <= score <= 75000 and 0 <= points <= 300):
        print("❌ Score or points out of valid range.")
        return
    absent_override  = _to_bool01(args[4]) if len(args) >= 5 else None
    checkin_override = _to_bool01(args[5]) if len(args) == 6 else None

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        try:
            player_id = int(player_in)
        except ValueError:
            cur.execute("""
                SELECT id, name, alias FROM players
                WHERE name LIKE ? OR alias LIKE ?
            """, (f"%{player_in}%", f"%{player_in}%"))
            matches = cur.fetchall()
            if len(matches) == 0:
                print(f"❌ No player found matching: {player_in}")
                return
            if len(matches) > 1:
                print(f"⚠️ Multiple players found for '{player_in}':")
                for pid, name, alias in matches:
                    print(f"  ID {pid}: {name} (alias: {alias})")
                return
            player_id = matches[0][0]

        absent  = absent_override  if absent_override  is not None else _compute_absent(conn, match_id, player_id)
        checkin = checkin_override if checkin_override is not None else 0

        existing = _fetch_ms_by_unique(cur, match_id, player_id)
        if existing:
            ms_id, old_score, old_points, old_absent, old_checkin = existing
            changed = (old_score != score or old_points != points or (old_absent or 0) != absent or (old_checkin or 0) != checkin)
            cur.execute("""UPDATE matchscore
                           SET score=?, points=?, absent=?, checkin=?
                           WHERE id=?""",
                        (score, points, absent, checkin, ms_id))
            conn.commit()
            print("CHANGED" if changed else "UNCHANGED")
        else:
            cur.execute("""INSERT INTO matchscore (match_id, player_id, score, points, absent, checkin)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (match_id, player_id, score, points, absent, checkin))
            conn.commit()
            print("CHANGED")

def delete_score(score_id):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        row = _fetch_score_by_id(cur, score_id)
        if not row:
            print("⚠️ Not found.")
            return
        conn.execute("DELETE FROM matchscore WHERE id = ?", (score_id,))
        print("OK DELETED:")
        print(f"ID={row[0]} match={row[1]} date={row[2]} opp={row[3]} "
              f"player={row[6]} score={row[7]} points={row[8]} absent={int(row[9] or 0)} checkin={int(row[10] or 0)}")

def list_scores(*args):
    show_all, season_filter, match_filter = _parse_list_args(args)
    rows = _query_rows(season_filter, match_filter, force_current_when_all=show_all)
    if not rows:
        print("⚠️ No scores found.")
        return
    if not show_all and not match_filter:
        last_mid = rows[0][1]
        rows = [r for r in rows if r[1] == last_mid]

    def print_block(block):
        match_id = block[0][1]; match_date = block[0][2]; opponent = block[0][3]; season_name = block[0][4]
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT score_ladys, score_opponent FROM match WHERE id = ?", (match_id,))
            sl, so = cur.fetchone() or (0, 0)
        print(f"📊 Match {match_id} – {opponent} | {match_date} | Season {season_name}")
        if sl or so:
            emoji = "🏆" if sl > so else ("😢" if sl < so else "🤝")
            print(f"Result: {sl} : {so} {emoji}")
        print()
        print(f"{'ID':<6} {'PID':<6} {'Player':<16} {'Score':>5} {'Pts':>3}")
        print("-" * 41)
        for r in block:
            print(f"{r[0]:<6} {r[7]:<6} {r[6]:<16.16} {r[8]:>5} {r[9]:>3}")
        print()

    if show_all or match_filter:
        group, current = [], None
        for r in rows:
            if current is None:
                current = r[1]
            if r[1] != current:
                print_block(group); group = []; current = r[1]
            group.append(r)
        if group: print_block(group)
    else:
        print_block(rows)

def list_scores_short(*args):
    show_all, season_filter, match_filter = _parse_list_args(args)
    rows = _query_rows(season_filter, match_filter, force_current_when_all=show_all)
    if not rows:
        print("⚠️ No scores found.")
        return
    if not show_all and not match_filter:
        last_mid = rows[0][1]
        rows = [r for r in rows if r[1] == last_mid]

    def print_block(block):
        match_id = block[0][1]; match_date = block[0][2]; opponent = block[0][3]
        print(f"Match {match_id} – {opponent} | {match_date}")
        print(f"{'ID':<6} {'Player':<16} {'Score':>5} {'Pts':>3}")
        print("-" * 34)
        for r in block:
            print(f"{r[0]:<6} {r[6]:<16.16} {r[8]:>5} {r[9]:>3}")
        print()

    if show_all or match_filter:
        group, current = [], None
        for r in rows:
            if current is None:
                current = r[1]
            if r[1] != current:
                print_block(group); group = []; current = r[1]
            group.append(r)
        if group: print_block(group)
    else:
        print_block(rows)

def edit_score(args):
    if not args or not str(args[0]).isdigit():
        print("Usage: matchscore edit <id> [--score <0..75000>] [--points <0..300>] "
              "[--absent true|false|toggle] [--checkin true|false|toggle]")
        return

    score_id = _parse_int(args[0])
    new_score = None
    new_points = None
    new_absent = None
    new_checkin = None
    toggle_absent = False
    toggle_checkin = False

    i = 1
    while i < len(args):
        tok = args[i]
        if tok == "--score" and i + 1 < len(args):
            new_score = _parse_int(args[i + 1], None); i += 2
        elif tok == "--points" and i + 1 < len(args):
            new_points = _parse_int(args[i + 1], None); i += 2
        elif tok == "--absent" and i + 1 < len(args):
            val = args[i + 1].strip().lower()
            if val == "toggle": toggle_absent = True
            else: new_absent = _to_bool01(val)
            i += 2
        elif tok == "--checkin" and i + 1 < len(args):
            val = args[i + 1].strip().lower()
            if val == "toggle": toggle_checkin = True
            else: new_checkin = _to_bool01(val)
            i += 2
        else:
            i += 1

    if new_score is None and new_points is None and new_absent is None and new_checkin is None and not (toggle_absent or toggle_checkin):
        print("⚠️ Nothing to update.")
        return

    with sqlite3.connect(DB_PATH) as conn:
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

        sets, vals = [], []
        if new_score is not None:
            if not (0 <= new_score <= 75000):
                print("❌ Score out of range."); return
            sets.append("score=?"); vals.append(new_score)
        if new_points is not None:
            if not (0 <= new_points <= 300):
                print("❌ Points out of range."); return
            sets.append("points=?"); vals.append(new_points)
        if new_absent is not None:
            sets.append("absent=?"); vals.append(new_absent)
        if new_checkin is not None:
            sets.append("checkin=?"); vals.append(new_checkin)

        if (new_score is not None or new_points is not None) and new_absent is None:
            computed = _compute_absent(conn, match_id, player_id)
            sets.append("absent=?"); vals.append(computed)

        if not sets:
            print("⚠️ Nothing to update."); return

        vals.append(score_id)
        cur.execute(f"UPDATE matchscore SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()

        row = _fetch_score_by_id(cur, score_id)
        if not row:
            print("OK UPDATED"); return
        print("\nOK UPDATED:")
        print(f"Match {row[1]} – {row[3]} | {row[2]}")
        print(f"{'ID':<6} {'Player':<16} {'Score':>5} {'Pts':>3} {'Abs':>3} {'Cin':>3}")
        print("-" * 46)
        print(f"{row[0]:<6} {row[6]:<16.16} {row[7]:>5} {row[8]:>3} {int(row[9] or 0):>3} {int(row[10] or 0):>3}")
        print()

