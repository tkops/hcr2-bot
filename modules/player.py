import sqlite3
import sys
import re
from datetime import datetime

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

    elif cmd == "list-active":
        sort = "gp"
        team = get_arg_value(args, "--team")
        if team:
            team = team.upper()
        if "--sort" in args:
            sort = get_arg_value(args, "--sort") or sort
        show_players(active_only=True, sort_by=sort, team_filter=team)

    elif cmd == "add":
        if len(args) < 1:
            print(
                "Usage: player add <team> <name> [alias] [gp] [active] [birthday: dd.mm.]")
            print(
                "       alias is required for PLTE and must be unique")
            return

        team_raw = args[0].upper()
        name = args[1] if len(args) > 1 else None
        alias = args[2] if len(args) > 2 else None
        gp = int(args[3]) if len(args) > 3 else 0
        active = args[4].lower() != "false" if len(args) > 4 else True
        birthday_raw = args[5] if len(args) > 5 else None

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

        add_player(name=name, alias=alias, gp=gp, active=active, birthday=birthday, team=team_raw)

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
            SELECT id, name, alias, garage_power, active, created_at, birthday, team
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
            print(f"{'ID':<3} {'Name':<20} {'Alias'}")
            print("-" * 40)
            for pid, name, alias, *_ in rows:
                print(f"{pid:<3} {name:<20} {alias or '-'}")
            print("-" * 40)
            print(f"🧩 Players in team {team_filter}: {len(rows)}")
        else:
            cur.execute("SELECT COUNT(*) FROM players WHERE active = 1")
            active_count = cur.fetchone()[0]

            print(f"{'ID':<3} {'Name':<15} {'Alias':<12} {'GP':>6} {'Act':<4} {'Birthday':<10} {'Team':<6} {'Created'}")
            print("-" * 85)
            for row in rows:
                pid, name, alias, gp, active, created, birthday, team = row
                bday_fmt = format_birthday(birthday)
                print(f"{pid:<3} {name:<15} {alias or '':<12} {gp:>6} {str(bool(active)):>4} {bday_fmt:<10} {team or '-':<6} {created}")
            print("-" * 85)
            print(f"🟢 Active players: {active_count}")


def add_player(name, alias=None, gp=0, active=True, birthday=None, team=None):
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
                INSERT INTO players (name, alias, garage_power, active, birthday, team)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, alias, gp, int(active), birthday, team)
            )
    else:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO players (name, alias, garage_power, active, birthday, team)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, alias, gp, int(active), birthday, team)
            )

    print(f"✅ Player '{name}' added.")


def edit_player(args):
    if len(args) < 1:
        print(
            "Usage: player edit <id> [--name NAME] [--alias ALIAS] [--gp GP] [--active true|false] [--birthday DD.MM.] [--team TEAM]")
        return

    pid = int(args[0])
    name = alias = birthday = team = None
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

        if not fields:
            print("⚠️  Nothing to update.")
            return

        values.append(pid)
        query = f"UPDATE players SET {', '.join(fields)} WHERE id = ?"
        conn.execute(query, values)

    print(f"✅ Player {pid} updated.")


def deactivate_player(pid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE players SET active = 0 WHERE id = ?", (pid,))
    print(f"🟡 Player {pid} deactivated.")


def delete_player(pid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM players WHERE id = ?", (pid,))
    print(f"🗑️  Player {pid} deleted.")


def print_help():
    print("Usage: python hcr2.py player <command> [args]")
    print("\nAvailable commands:")
    print("  list [--sort gp|name] [--team TEAM]         Show all players")
    print("  list-active [--sort gp|name] [--team TEAM]  Show only active players")
    print("  add <team> <name> [alias] [gp] [active] [birthday: dd.mm.]")
    print("  edit <id> --gp 90000 --team PL3 --birthday 15.07. ...")
    print("  deactivate <id>               Set player inactive")
    print("  delete <id>                   Remove player")

