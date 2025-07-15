import sqlite3

DB_PATH = "db/hcr2.db"

def handle_command(cmd, args):
    if cmd == "add":
        add_score(args)
    elif cmd == "list":
        if args:
            list_scores(int(args[0]))
        else:
            list_scores()
    elif cmd == "delete":
        if len(args) != 1:
            print("Usage: matchscore delete <id>")
            return
        delete_score(int(args[0]))
    elif cmd == "edit":
        edit_score(args)
    else:
        print(f"❌ Unknown matchscore command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py matchscore <command> [args]")
    print("\nAvailable commands:")
    print("  add <match_id> <player_id> <score>")
    print("  list [match_id]")
    print("  delete <id>")
    print("  edit <id> --score <newscore>")

def add_score(args):
    if len(args) != 3:
        print("Usage: matchscore add <match_id> <player_id> <score>")
        return

    match_id = int(args[0])
    player_id = int(args[1])
    score = int(args[2])

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO matchscore (match_id, player_id, score) VALUES (?, ?, ?)",
            (match_id, player_id, score)
        )

    print(f"✅ Score added for player {player_id} in match {match_id}: {score}")

def list_scores(match_id=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        if match_id:
            cur.execute("""
                SELECT ms.id, ms.score, p.name, m.id
                FROM matchscore ms
                JOIN players p ON ms.player_id = p.id
                JOIN match m ON ms.match_id = m.id
                WHERE ms.match_id = ?
                ORDER BY ms.score DESC
            """, (match_id,))
        else:
            cur.execute("""
                SELECT ms.id, ms.score, p.name, m.id
                FROM matchscore ms
                JOIN players p ON ms.player_id = p.id
                JOIN match m ON ms.match_id = m.id
                ORDER BY m.id DESC, ms.score DESC
            """)
        rows = cur.fetchall()

    print(f"{'ID':<3} {'Match':<5} {'Player':<20} {'Score'}")
    print("-" * 50)
    for rid, score, name, mid in rows:
        print(f"{rid:<3} {mid:<5} {name:<20} {score}")

def delete_score(sid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM matchscore WHERE id = ?", (sid,))
    print(f"🗑️  Matchscore {sid} deleted.")

def edit_score(args):
    if len(args) != 3 or args[1] != "--score":
        print("Usage: matchscore edit <id> --score <newscore>")
        return

    sid = int(args[0])
    new_score = int(args[2])

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE matchscore SET score = ? WHERE id = ?", (new_score, sid))

    print(f"✅ Score updated for matchscore {sid}: {new_score}")

