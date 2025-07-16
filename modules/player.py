import sqlite3
import sys
import re
from datetime import datetime

DB_PATH = "db/hcr2.db"


def handle_command(cmd, args):
    if cmd == "list":
        sort = "gp"
        if args and args[0] == "--sort" and len(args) > 1:
            sort = args[1]
        show_players(active_only=False, sort_by=sort)
    elif cmd == "list-active":
        sort = "gp"
        if args and args[0] == "--sort" and len(args) > 1:
            sort = args[1]
        show_players(active_only=True, sort_by=sort)
    elif cmd == "add":
        if len(args) < 1:
            print(
                "Usage: player add <name> [alias] [garage_power] [active] [birthday: dd.mm.] [team]")
            return
        name = args[0]
        alias = args[1] if len(args) > 1 else None
        gp = int(args[2]) if len(args) > 2 else 0
        active = args[3].lower() != "false" if len(args) > 3 else True
        birthday_raw = args[4] if len(args) > 4 else None
        team_raw = args[5] if len(args) > 5 else None

        birthday = parse_birthday(birthday_raw) if birthday_raw else None
        if birthday_raw and not birthday:
            print(
                f"❌ Ungültiges Geburtstag-Format: {birthday_raw} (erlaubt: DD.MM.)")
            return

        team = team_raw if team_raw else None
        if team and not is_valid_team(team):
            print(
                f"❌ Ungültiger Teamname: {team} (nur PLTE oder PL1–PL9 erlaubt)")
            return

        add_player(name, alias, gp, active, birthday, team)
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


def show_players(active_only=False, sort_by="gp"):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        q = """
            SELECT id, name, alias, garage_power, active, created_at, birthday, team
            FROM players
        """
        if active_only:
            q += " WHERE active = 1"

        if sort_by == "name":
            q += " ORDER BY name COLLATE NOCASE"
        else:
            q += " ORDER BY garage_power DESC"

        cur.execute(q)
        rows = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM players WHERE active = 1")
        active_count = cur.fetchone()[0]

    print(f"{'ID':<3} {'Name':<15} {'Alias':<12} {'GP':>6} {'Act':<4} {'Geburtstag':<10} {'Team':<6} {'Erstellt'}")
    print("-" * 85)
    for row in rows:
        pid, name, alias, gp, active, created, birthday, team = row
        bday_fmt = format_birthday(birthday)
        print(f"{pid:<3} {name:<15} {alias or '':<12} {gp:>6} {str(bool(active)):>4} {bday_fmt:<10} {team or '-':<6} {created}")
    print("-" * 85)
    print(f"🟢 Active players: {active_count}")


def add_player(name, alias=None, gp=0, active=True, birthday=None, team=None):
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
                print(
                    f"❌ Ungültiges Geburtstag-Format: {raw} (erlaubt: DD.MM.)")
                return
        elif args[i] == "--team":
            i += 1
            team = args[i]
            if not is_valid_team(team):
                print(
                    f"❌ Ungültiger Teamname: {team} (nur PLTE oder PL1–PL9 erlaubt)")
                return
        i += 1

    fields = []
    values = []

    if name:
        fields.append("name = ?")
        values.append(name)
    if alias:
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

    with sqlite3.connect(DB_PATH) as conn:
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
    print("  list [--sort gp|name]         Show all players")
    print("  list-active [--sort gp|name]  Show only active players")
    print("  add <name> [alias] [gp] [active] [birthday: dd.mm.] [team]")
    print("  edit <id> --gp 90000 --team PL3 --birthday 15.07. ...")
    print("  deactivate <id>               Set player inactive")
    print("  delete <id>                   Remove player")
