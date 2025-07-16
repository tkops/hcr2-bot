import sqlite3

DB_PATH = "db/hcr2.db"


def handle_command(cmd, args):
    if cmd == "add":
        add_match(args)
    elif cmd == "list":
        if args:
            list_matches(season_number=int(args[0]))
        else:
            list_matches()
    elif cmd == "delete":
        if len(args) != 1:
            print("Usage: match delete <id>")
            return
        delete_match(int(args[0]))
    else:
        print(f"❌ Unknown match command: {cmd}")
        print_help()


def print_help():
    print("Usage: python hcr2.py match <command> [args]")
    print("\nAvailable commands:")
    print("  add <teamevent_id> <season_number> <start> <opponent>")
    print("  list [season_number]")
    print("  delete <id>")


def add_match(args):
    if len(args) < 4:
        print("Usage: match add <teamevent_id> <season_number> <start> <opponent>")
        return

    teamevent_id = int(args[0])
    season_number = int(args[1])
    start = args[2]
    opponent = args[3]

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO match (teamevent_id, season_number, start, opponent) VALUES (?, ?, ?, ?)",
            (teamevent_id, season_number, start, opponent)
        )

    print(
        f"✅ Match added: Event {teamevent_id}, Season {season_number}, vs {opponent} on {start}")


def list_matches(season_number=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        if season_number:
            cur.execute("""
                SELECT m.id, m.start, m.opponent, t.name
                FROM match m
                JOIN teamevent t ON m.teamevent_id = t.id
                WHERE m.season_number = ?
                ORDER BY m.start DESC
                LIMIT 15
            """, (season_number,))
        else:
            cur.execute("""
                SELECT m.id, m.start, m.opponent, t.name
                FROM match m
                JOIN teamevent t ON m.teamevent_id = t.id
                ORDER BY m.start DESC
                LIMIT 15
            """)
        matches = cur.fetchall()

    print(f"{'ID':<5}   {'Start':<12} {'Opponent':<25} {'Event'}")
    print("-" * 65)
    for mid, start, opp, event_name in matches:
        print(f"{mid:>5}.  {start:<12} {opp:<25} {event_name}")


def delete_match(mid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM match WHERE id = ?", (mid,))
    print(f"🗑️  Match {mid} deleted.")
