import sqlite3

DB_PATH = "db/hcr2.db"

def handle_command(cmd, args):
    if cmd == "add":
        add_season(args)
    elif cmd == "list":
        list_seasons()
    else:
        print(f"❌ Unknown season command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py season <command> [args]")
    print("\nAvailable commands:")
    print("  add <number> <name> <start> <division>")
    print("      e.g. add 51 'Juli 2025' 2025-07-01 CC")
    print("  list")

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
        cur.execute("SELECT id, number, name, start, division FROM season ORDER BY start DESC")
        rows = cur.fetchall()

    print(f"{'ID':<3} {'No.':<4} {'Start':<10} {'Division':<6} Name")
    print("-" * 50)
    for row in rows:
        sid, number, name, start, division = row
        print(f"{sid:<3} {number:<4} {start:<10} {division:<6} {name}")

