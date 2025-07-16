import sqlite3

DB_PATH = "db/hcr2.db"


def handle_command(cmd, args):
    if cmd == "add":
        add_season(args)
    elif cmd == "list":
        list_seasons()
    elif cmd == "edit":
        edit_season(args)
    else:
        print(f"❌ Unknown season command: {cmd}")
        print_help()


def print_help():
    print("Usage: python hcr2.py season <command> [args]")
    print("\nAvailable commands:")
    print("  list")
    print("  add <number> <name> <start> <division>")
    print("      e.g. add 51 'Juli 2025' 2025-07-01 Div1")
    print("      e.g. add 52 'August 2025' 2025-08-01 CC")
    print(
        "  edit <id> [--number N] [--name TEXT] [--start DATE] [--division TEXT]")


def add_season(args):
    if len(args) != 4:
        print("Usage: season add <number> <name> <start> <division>")
        return

    number = int(args[0])
    name = args[1]
    start = args[2]
    division = args[3]

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO season (number, name, start, division) VALUES (?, ?, ?, ?)",
            (number, name, start, division)
        )

    print(f"✅ Season {number} ('{name}') added in division {division}")


def list_seasons():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT number, name, start, division FROM season ORDER BY start DESC")
        rows = cur.fetchall()

    print(f"{'No.':<4} {'Start':<10} {'Division':<8} Name")
    print("-" * 50)
    for number, name, start, division in rows:
        print(f"{number:<4} {start:<10} {division:<8} {name}")


def edit_season(args):
    if len(args) < 2:
        print(
            "Usage: season edit <number> [--name TEXT] [--start DATE] [--division TEXT]")
        return

    number = int(args[0])
    updates = {}
    i = 1
    while i < len(args):
        if args[i] == "--name":
            updates["name"] = args[i+1]
            i += 2
        elif args[i] == "--start":
            updates["start"] = args[i+1]
            i += 2
        elif args[i] == "--division":
            updates["division"] = args[i+1]
            i += 2
        else:
            print(f"❌ Unknown option: {args[i]}")
            return

    if not updates:
        print("❌ Nothing to update.")
        return

    set_clause = ", ".join(f"{field} = ?" for field in updates)
    values = list(updates.values()) + [number]

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            f"UPDATE season SET {set_clause} WHERE number = ?", values)

    print(f"✅ Season {number} updated: {', '.join(updates.keys())}")
