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
    else:
        print(f"❌ Unknown matchscore command: {cmd}")
        print_help()


def print_help():
    print("Usage: python hcr2.py matchscore <command> [args]")
    print("\nAvailable commands:")
    print("  add <match_id> <player_id|name> <score> <points>")
    print("  list [--match <id>] [--season [<number>]]")
    print("  delete <id>")
    print("  edit <id> [--score <newscore>] [--points <newpoints>]")


def add_score(args):
    if len(args) != 4:
        print("Usage: matchscore add <match_id> <player_id|name> <score> <points>")
        return

    match_id = int(args[0])
    player_input = args[1]
    score = int(args[2])
    points = int(args[3])

    if not (0 <= score <= 75000):
        print("❌ Invalid score. Must be between 0 and 75000.")
        return

    if not (0 <= points <= 300):
        print("❌ Invalid points. Must be between 0 and 300.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        try:
            player_id = int(player_input)
        except ValueError:
            cur.execute("""
                SELECT id, name, alias FROM players
                WHERE name LIKE ? OR alias LIKE ?
            """, (f"%{player_input}%", f"%{player_input}%"))
            matches = cur.fetchall()

            if len(matches) == 0:
                print(f"❌ No player found matching: {player_input}")
                return
            elif len(matches) > 1:
                print(f"⚠️ Multiple players found for '{player_input}':")
                for pid, name, alias in matches:
                    print(f"  ID {pid}: {name} (alias: {alias})")
                return
            else:
                player_id = matches[0][0]

        conn.execute("""
            INSERT INTO matchscore (match_id, player_id, score, points)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(match_id, player_id) DO UPDATE SET
                score=excluded.score,
                points=excluded.points
        """, (match_id, player_id, score, points))

        cur.execute("""
            SELECT ms.id, m.id, m.start, m.opponent,
                   s.name, s.division, p.name, ms.score, ms.points
            FROM matchscore ms
            JOIN match m ON ms.match_id = m.id
            JOIN season s ON m.season_number = s.number
            JOIN players p ON ms.player_id = p.id
            WHERE ms.match_id = ? AND ms.player_id = ?
        """, (match_id, player_id))

        row = cur.fetchone()

        print(f"\n✅ Score saved:")
        print(f"{'ID':<3} {'Match':<6} {'Date':<10} {'Opponent':<15} {'Season':<12} "
              f"{'Div':<6} {'Player':<20} {'Score':<6} {'Points'}")
        print("-" * 100)
        print(f"{row[0]:<3} {row[1]:<6} {row[2]:<10} {row[3]:<15} {row[4]:<12} "
              f"{row[5]:<6} {row[6]:<20} {row[7]:<6} {row[8]}")


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

    print(f"{'ID':<3} {'Match':<5} {'Date':<10} {'Opponent':<15} "
          f"{'Season':<12} {'Div':<5} {'Player':<20} {'Score':<6} {'Points'}")
    print("-" * 100)
    for sid, mid, date, opponent, season, division, player, score, points in rows:
        print(f"{sid:<3} {mid:<5} {date:<10} {opponent:<15} "
              f"{season:<12} {division:<5} {player:<20} {score:<6} {points}")


def delete_score(sid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM matchscore WHERE id = ?", (sid,))
    print(f"🗑️  Matchscore {sid} deleted.")


def edit_score(args):
    if len(args) < 3:
        print("Usage: matchscore edit <id> [--score <newscore>] [--points <newpoints>]")
        return

    sid = int(args[0])
    new_score = None
    new_points = None

    i = 1
    while i < len(args):
        if args[i] == "--score":
            i += 1
            new_score = int(args[i])
            if not (0 <= new_score <= 75000):
                print("❌ Invalid score. Must be between 0 and 75000.")
                return
        elif args[i] == "--points":
            i += 1
            new_points = int(args[i])
            if not (0 <= new_points <= 300):
                print("❌ Invalid points. Must be between 0 and 300.")
                return
        i += 1

    if new_score is None and new_points is None:
        print("⚠️ Nothing to update.")
        return

    fields = []
    values = []

    if new_score is not None:
        fields.append("score = ?")
        values.append(new_score)
    if new_points is not None:
        fields.append("points = ?")
        values.append(new_points)

    values.append(sid)
    query = f"UPDATE matchscore SET {', '.join(fields)} WHERE id = ?"

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(query, values)

    print(f"✅ Matchscore {sid} updated.")

