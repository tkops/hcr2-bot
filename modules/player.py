import sqlite3
import sys

DB_PATH = "db/hcr2.db"

def handle_command(cmd, args):
    if cmd == "list":
        show_players(active_only=False)
    elif cmd == "list-active":
        show_players(active_only=True)
    elif cmd == "add":
        if len(args) < 1:
            print("Usage: player add <name> [alias] [garage_power] [active]")
            return
        name = args[0]
        alias = args[1] if len(args) > 1 else None
        gp = int(args[2]) if len(args) > 2 else 0
        active = args[3].lower() != "false" if len(args) > 3 else True
        add_player(name, alias, gp, active)
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

def show_players(active_only=False):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        q = "SELECT id, name, alias, garage_power, active, created_at FROM players"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY name COLLATE NOCASE"
        cur.execute(q)
        rows = cur.fetchall()

    print(f"{'ID':<5} {'Name':<20} {'Alias':<20} {'GP':>6} {'Active':<6} {'Created'}")
    print("-" * 81)
    for row in rows:
        pid, name, alias, gp, active, created = row
        print(f"{pid:<5} {name:<20} {alias or '':<20} {gp:>6} {str(bool(active)):>6} {created}")

def add_player(name, alias=None, gp=0, active=True):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO players (name, alias, garage_power, active) VALUES (?, ?, ?, ?)",
            (name, alias, gp, int(active))
        )
    print(f"✅ Player '{name}' added.")

def edit_player(args):
    if len(args) < 1:
        print("Usage: player edit <id> [--name NAME] [--alias ALIAS] [--gp GP] [--active true|false]")
        return

    pid = int(args[0])
    name = alias = None
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
    print("  list                     Show all players")
    print("  list-active              Show only active players")
    print("  add <name> [alias] [...] Add player")
    print("  edit <id> [...]          Edit player (e.g. --gp 80000)")
    print("  deactivate <id>          Set player inactive")
    print("  delete <id>              Remove player")

