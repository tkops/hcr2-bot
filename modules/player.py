import sqlite3
import sys
import re
from datetime import datetime, timedelta

DB_PATH = "db/hcr2.db"

def handle_command(cmd, args):
    if cmd == "list":
        sort = "gp"
        team = get_arg_value(args, "--team")
        if team:
            team = team.upper()
        if "--sort" in args:
            sort = get_arg_value(args, "--sort") or sort
        show_players(active_only=False, sort_by=sort, team_filter=team)

    elif cmd == "activate":
        if len(args) != 1:
            print("Usage: player activate <id>")
            return
        activate_player(int(args[0]))

    elif cmd == "list-active":
        sort = "gp"
        team = get_arg_value(args, "--team")
        if team:
            team = team.upper()
        if "--sort" in args:
            sort = get_arg_value(args, "--sort") or sort
        show_players(active_only=True, sort_by=sort, team_filter=team)

    elif cmd == "show":
        if len(args) != 1:
            print("Usage: player show <id>")
            return
        try:
            pid = int(args[0])
            show_player(pid)
        except ValueError:
            print("❌ Invalid ID.")

    elif cmd == "add":
        if len(args) < 1:
            print("Usage: player add <team> <name> [alias] [gp] [active] [birthday: dd.mm.] [discord_name]")
            print("       alias is required for PLTE and must be unique")
            return

        team_raw = args[0].upper()
        name = args[1] if len(args) > 1 else None
        alias = args[2] if len(args) > 2 else None
        gp = int(args[3]) if len(args) > 3 else 0
        active = args[4].lower() != "false" if len(args) > 4 else True
        birthday_raw = args[5] if len(args) > 5 else None
        discord_name = args[6] if len(args) > 6 else None

        if not name:
            print("❌ Name is required.")
            return

        if not is_valid_team(team_raw):
            print("❌ Invalid team name. Allowed: PLTE or PL1–PL9")
            return

        birthday = parse_birthday(birthday_raw) if birthday_raw else None
        if birthday_raw and not birthday:
            print(f"❌ Invalid birthday format: {birthday_raw} (use DD.MM.)")
            return

        add_player(name=name, alias=alias, gp=gp, active=active, birthday=birthday, team=team_raw, discord_name=discord_name)

    elif cmd == "edit":
        edit_player(args)

    elif cmd == "deactivate":
        if len(args) != 1:
            print("Usage: player deactivate <id>")
            return
        deactivate_player(int(args[0]))

    elif cmd == "delete":
        if len(args) != 1:
            print("Usage: player delete <id>")
            return
        delete_player(int(args[0]))

    elif cmd == "grep":
        if len(args) != 1:
            print("Usage: player grep <term>")
            return
        grep_players(args[0])

    # --- NEW: away/back driven by Discord name ---
    elif cmd == "away":
        dn = get_arg_value(args, "--discord")
        dur = get_arg_value(args, "--dur")  # accepts 1w..4w (optional 'w')
        if not dn:
            print("Usage: player away --discord <discord_name> [--dur 1w|2w|3w|4w]")
            return
        away_set_by_discord(dn, dur)

    elif cmd == "back":
        dn = get_arg_value(args, "--discord")
        if not dn:
            print("Usage: player back --discord <discord_name>")
            return
        away_clear_by_discord(dn)

    else:
        print(f"❌ Unknown player command: {cmd}")
        print_help()

def get_arg_value(args, key):
    if key in args:
        idx = args.index(key)
        if idx + 1 < len(args):
            return args[idx + 1]
    return None

def parse_birthday(raw):
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw.strip("."), "%d.%m")
        return dt.strftime("%m-%d")
    except ValueError:
        return None

def format_birthday(stored):
    if not stored:
        return "-"
    try:
        dt = datetime.strptime(stored, "%m-%d")
        return dt.strftime("%d.%m.")
    except ValueError:
        return stored

def is_valid_team(team):
    return team == "PLTE" or re.fullmatch(r"PL[1-9]", team) is not None

def show_players(active_only=False, sort_by="gp", team_filter=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        q = """
            SELECT id, name, alias, garage_power, active, created_at, birthday, team, discord_name
            FROM players
        """
        conditions = []
        if active_only:
            conditions.append("active = 1")
        if team_filter:
            conditions.append("UPPER(team) = ?")

        if conditions:
            q += " WHERE " + " AND ".join(conditions)

        if sort_by == "name":
            q += " ORDER BY name COLLATE NOCASE"
        else:
            q += " ORDER BY garage_power DESC"

        cur.execute(q, (team_filter,) if team_filter else ())
        rows = cur.fetchall()

        if team_filter:
            print(f"{'#':<3} {'ID':<4} {'Name':<20} {'Alias':<15}")
            print("-" * 60)
            for i, (pid, name, alias, *_) in enumerate(rows, start=1):
                print(f"{i:<3} {pid:<4} {name:<20} {alias or '-':<15}")
            print("-" * 60)
        else:
            cur.execute("SELECT COUNT(*) FROM players WHERE active = 1")
            active_count = cur.fetchone()[0]

            print(f"{'ID':<4} {'Name':<20} {'Alias':<15} {'GP':>6} {'Act':<5} {'Birthday':<10} {'Team':<7} {'Discord':<18} {'Created'}")
            print("-" * 120)
            for row in rows:
                pid, name, alias, gp, active, created, birthday, team, discord_name = row
                bday_fmt = format_birthday(birthday)
                print(f"{pid:<4} {name:<20} {alias or '':<15} {gp:>6} {str(bool(active)):>5} {bday_fmt:<10} {team or '-':<7} {discord_name or '-':<18} {created}")
            print("-" * 120)
            print(f"🟢 Active players: {active_count}")

def add_player(name, alias=None, gp=0, active=True, birthday=None, team=None, discord_name=None):
    alias = alias.strip() if alias else None

    if team == "PLTE":
        if not alias:
            print("❌ Alias is required for team PLTE.")
            return

        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, alias FROM players
                WHERE team = 'PLTE'
            """)
            for pid, existing_alias in cur.fetchall():
                if alias in existing_alias or existing_alias in alias:
                    print(f"❌ Alias conflict: '{alias}' vs '{existing_alias}' (ID {pid})")
                    return

            cur.execute(
                """
                INSERT INTO players (name, alias, garage_power, active, birthday, team, discord_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, alias, gp, int(active), birthday, team, discord_name)
            )
    else:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO players (name, alias, garage_power, active, birthday, team, discord_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, alias, gp, int(active), birthday, team, discord_name)
            )
    print(f"✅ Player '{name}' added.")

def edit_player(args):
    if len(args) < 1:
        print("Usage: player edit <id> [--name NAME] [--alias ALIAS] [--gp GP] [--active true|false] [--birthday DD.MM.] [--team TEAM] [--discord DISCORD]")
        return

    pid = int(args[0])
    name = alias = birthday = team = discord = None
    gp = active = None

    i = 1
    while i < len(args):
        if args[i] == "--name":
            i += 1
            name = args[i]
        elif args[i] == "--alias":
            i += 1
            alias = args[i]
        elif args[i] == "--gp":
            i += 1
            gp = int(args[i])
        elif args[i] == "--active":
            i += 1
            active = args[i].lower() == "true"
        elif args[i] == "--birthday":
            i += 1
            raw = args[i]
            birthday = parse_birthday(raw)
            if not birthday:
                print(f"❌ Invalid birthday format: {raw} (use DD.MM.)")
                return
        elif args[i] == "--team":
            i += 1
            team = args[i].upper()
            if not is_valid_team(team):
                print(f"❌ Invalid team name: {team} (allowed: PLTE or PL1–PL9)")
                return
        elif args[i] == "--discord":
            i += 1
            discord = args[i]
        i += 1

    if alias is not None:
        alias = alias.strip()

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        cur.execute("SELECT team, alias FROM players WHERE id = ?", (pid,))
        row = cur.fetchone()
        if not row:
            print(f"❌ Player ID {pid} not found.")
            return
        current_team, current_alias = row
        target_team = team or current_team
        target_alias = alias if alias is not None else current_alias

        if target_team == "PLTE":
            if not target_alias:
                print("❌ Alias is required for team PLTE.")
                return

            cur.execute("""
                SELECT id, alias FROM players
                WHERE team = 'PLTE' AND id != ?
            """, (pid,))
            for cid, calias in cur.fetchall():
                if target_alias in calias or calias in target_alias:
                    print(f"❌ Alias conflict: '{target_alias}' vs '{calias}' (ID {cid})")
                    return

        fields = []
        values = []

        if name:
            fields.append("name = ?")
            values.append(name)
        if alias is not None:
            fields.append("alias = ?")
            values.append(alias)
        if gp is not None:
            fields.append("garage_power = ?")
            values.append(gp)
        if active is not None:
            fields.append("active = ?")
            values.append(1 if active else 0)
        if birthday is not None:
            fields.append("birthday = ?")
            values.append(birthday)
        if team is not None:
            fields.append("team = ?")
            values.append(team)
        if discord is not None:
            fields.append("discord_name = ?")
            values.append(discord)

        if not fields:
            print("⚠️  Nothing to update.")
            return

        values.append(pid)
        query = f"UPDATE players SET {', '.join(fields)} WHERE id = ?"
        conn.execute(query, values)

    print(f"✅ Player {pid} updated.")
    show_player(pid)

def deactivate_player(pid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE players SET active = 0 WHERE id = ?", (pid,))
    print(f"🟡 Player {pid} deactivated.")

def delete_player(pid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM players WHERE id = ?", (pid,))
    print(f"🗑️  Player {pid} deleted.")

def grep_players(term):
    pattern = f"%{term.lower()}%"
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, alias, garage_power, active
            FROM players
            WHERE LOWER(name) LIKE ? OR LOWER(alias) LIKE ?
            ORDER BY name COLLATE NOCASE
        """, (pattern, pattern))
        rows = cur.fetchall()

    if not rows:
        print(f"❌ No players found matching '{term}'")
        return

    print(f"{'ID':<4} {'NAME':<20} {'Alias':<15} {'GP':>5} {'Act':>5}")
    print("-" * 55)
    for pid, name, alias, gp, active in rows:
        print(f"{pid:<4} {name:<20} {alias or '':<15} {gp:>5} {str(bool(active))[:1]}")
    print("-" * 55)

def activate_player(pid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE players SET active = 1 WHERE id = ?", (pid,))
    print(f"🟢 Player {pid} activated.")

def print_help():
    print("Usage: python hcr2.py player <command> [args]")
    print("\nAvailable commands:")
    print("  list [--sort gp|name] [--team TEAM]         Show all players")
    print("  list-active [--sort gp|name] [--team TEAM]  Show only active players")
    print("  add <team> <name> [alias] [gp] [active] [birthday: dd.mm.] [discord_name]")
    print("  edit <id> --gp 90000 --team PL3 --birthday 15.07. --discord foo#1234 ...")
    print("  deactivate <id>               Set player inactive")
    print("  delete <id>                   Remove player")
    print("  show <id>                     Show player details")
    print("  grep <term>                   Search players by name or alias (case-insensitive)")
    print("  activate <id>                 Set player active")
    print("  away --discord <name> [--dur 1w|2w|3w|4w]  Set away_from=now, away_until=now+dur")
    print("  back --discord <name>                      Clear away_from/away_until")

def show_player(pid):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, alias, garage_power, active, birthday, team, discord_name,
                   created_at, last_modified, active_modified, away_from, away_until
            FROM players
            WHERE id = ?
        """, (pid,))
        row = cur.fetchone()

        if not row:
            print(f"❌ Player ID {pid} not found.")
            return

        (id, name, alias, gp, active, birthday, team, discord,
         created, last_modified, active_modified, away_from, away_until) = row

        print(f"{'ID':<15}: {id}")
        print(f"{'Name':<15}: {name}")
        print(f"{'Alias':<15}: {alias or '-'}")
        print(f"{'Garage Power':<15}: {gp}")
        print(f"{'Active':<15}: {bool(active)}")
        print(f"{'Birthday':<15}: {format_birthday(birthday)}")
        print(f"{'Team':<15}: {team or '-'}")
        print(f"{'Discord':<15}: {discord or '-'}")
        print(f"{'Created':<15}: {created}")
        print(f"{'Last modified':<15}: {last_modified or '-'}")
        print(f"{'Active modified':<15}: {active_modified or '-'}")
        print(f"{'Away from':<15}: {away_from or '-'}")
        print(f"{'Away until':<15}: {away_until or '-'}")

# ------- NEW: away helpers -------

def _find_player_id_by_discord(discord_name: str):
    if not discord_name:
        return None
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM players
            WHERE LOWER(discord_name) = LOWER(?)
            LIMIT 1
        """, (discord_name.strip(),))
        row = cur.fetchone()
        return row[0] if row else None

def _parse_weeks_token(token: str) -> int:
    """Accepts 1w..4w (optional 'w'); returns days 7..28. Default 1w."""
    if not token:
        return 7
    m = re.fullmatch(r"\s*([1-4])\s*w?\s*", token, flags=re.IGNORECASE)
    if not m:
        raise ValueError("Use 1w, 2w, 3w or 4w.")
    return int(m.group(1)) * 7

def away_set_by_discord(discord_name: str, dur_token: str = None):
    pid = _find_player_id_by_discord(discord_name)
    if not pid:
        print(f"❌ No player found for discord_name='{discord_name}'")
        return
    try:
        days = _parse_weeks_token(dur_token)
    except ValueError as e:
        print(f"❌ {e}")
        return

    now = datetime.now()
    away_from = now.strftime("%Y-%m-%d %H:%M:%S")
    away_until = (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE players
               SET away_from = ?, away_until = ?
             WHERE id = ?
        """, (away_from, away_until, pid))
    print(f"✅ Away set for player {pid}\nfrom: {away_from}\nuntil: {away_until}")

def away_clear_by_discord(discord_name: str):
    pid = _find_player_id_by_discord(discord_name)
    if not pid:
        print(f"❌ No player found for discord_name='{discord_name}'")
        return
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE players
               SET away_from = NULL, away_until = NULL
             WHERE id = ?
        """, (pid,))
    print(f"✅ Back: absence cleared for player {pid}")

