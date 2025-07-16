import sqlite3

DB_PATH = "db/hcr2.db"

def handle_command(cmd, args):
    if cmd == "add":
        add_score(args)
    elif cmd == "list":
        list_scores(*args)
    elif cmd == "delete":
        if len(args) != 1:
            print("Usage: matchscore delete <id>")
            return
        delete_score(int(args[0]))
    elif cmd == "edit":
        edit_score(args)
    elif cmd == "autoadd":
        if len(args) != 1:
            print("Usage: matchscore autoadd <match_id>")
            return
        auto_add_scores(int(args[0]))
    else:
        print(f"❌ Unknown matchscore command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py matchscore <command> [args]")
    print("\nAvailable commands:")
    print("  add <match_id> <player_id> <score> <points>")
    print("  list [--match <id>] [--season [<number>]]")
    print("  delete <id>")
    print("  edit <id> [--score <newscore>] [--points <newpoints>]")
    print("  autoadd <match_id>")

def list_scores(*args):
    match_id = None
    season_number = None
    auto_latest_season = False

    i = 0
    while i < len(args):
        if args[i] == "--match":
            match_id = int(args[i + 1])
            i += 2
        elif args[i] == "--season":
            if i + 1 < len(args) and args[i + 1].isdigit():
                season_number = int(args[i + 1])
                i += 2
            else:
                auto_latest_season = True
                i += 1
        else:
            print(f"❌ Unknown option: {args[i]}")
            return

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if auto_latest_season:
            cur.execute("SELECT MAX(number) FROM season")
            result = cur.fetchone()
            if result and result[0] is not None:
                season_number = result[0]
            else:
                print("⚠️ No seasons found.")
                return

        base_query = """
            SELECT
                ms.id,
                m.id AS match_id,
                m.start,
                m.opponent,
                s.name AS season_name,
                s.division,
                p.name AS player_name,
                ms.score,
                ms.points
            FROM matchscore ms
            JOIN players p ON ms.player_id = p.id
            JOIN match m ON ms.match_id = m.id
            JOIN season s ON m.season_number = s.number
        """

        where = ""
        values = ()

        if match_id:
            where = "WHERE m.id = ?"
            values = (match_id,)
        elif season_number:
            where = "WHERE m.season_number = ?"
            values = (season_number,)

        cur.execute(f"""
            {base_query}
            {where}
            ORDER BY m.start DESC, ms.score DESC
        """, values)

        rows = cur.fetchall()

    print(f"{'ID':<3} {'Match':<5} {'Date':<10} {'Opponent':<15} {'Season':<12} {'Div':<5} {'Player':<20} {'Score':<6} {'Points'}")
    print("-" * 100)
    for sid, mid, date, opponent, season, division, player, score, points in rows:
        print(f"{sid:<3} {mid:<5} {date:<10} {opponent:<15} {season:<12} {division:<5} {player:<20} {score:<6} {points}")

