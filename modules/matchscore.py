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
        if len(args) > 1:
            print("Usage: matchscore autoadd [<match_id>]")
            return
        match_id = int(args[0]) if args else get_latest_match_id()
        if match_id is None:
            print("❌ No match found.")
            return
        auto_add_scores(match_id)
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
    print("  autoadd [<match_id>]")

def get_latest_match_id():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT MAX(id) FROM match")
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None


def add_score(args):
    if len(args) != 4:
        print("Usage: matchscore add <match_id> <player_id|name> <score> <points>")
        return

    match_id = int(args[0])
    player_input = args[1]
    score = int(args[2])
    points = int(args[3])

    if not (0 <= score <= 75000 and 0 <= points <= 300):
        print("❌ Score or points out of valid range.")
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

        cur.execute("""
            SELECT score, points FROM matchscore
            WHERE match_id = ? AND player_id = ?
        """, (match_id, player_id))
        existing = cur.fetchone()

        changed = False
        if existing:
            old_score, old_points = existing
            changed = (score != old_score or points != old_points)
        else:
            changed = True

        try:
            conn.execute("""
                INSERT INTO matchscore (match_id, player_id, score, points)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(match_id, player_id)
                DO UPDATE SET score = excluded.score, points = excluded.points
            """, (match_id, player_id, score, points))
        except Exception as e:
            print(f"❌ Failed to save score: match={match_id}, player={player_input}, score={score}, points={points}")
            print(f"Error: {e}")
            return

        print("CHANGED" if changed else "UNCHANGED")

def delete_score(score_id):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT ms.id, m.id, m.start, m.opponent,
                   s.name, s.division, p.name, ms.score, ms.points
            FROM matchscore ms
            JOIN match m ON ms.match_id = m.id
            JOIN season s ON m.season_number = s.number
            JOIN players p ON ms.player_id = p.id
            WHERE ms.id = ?
        """, (score_id,))
        row = cur.fetchone()

        if not row:
            print(f"⚠️ No entry found with ID {score_id}.")
            return

        conn.execute("DELETE FROM matchscore WHERE id = ?", (score_id,))
        print(f"\n🗑️ Score entry deleted:")
        print(f"{'ID':<3} {'Match':<6} {'Date':<10} {'Opponent':<15} {'Season':<12} {'Div':<6} {'Player':<20} {'Score':<6} {'Points'}")
        print("-" * 100)
        print(f"{row[0]:<3} {row[1]:<6} {row[2]:<10} {row[3]:<15} {row[4]:<12} {row[5]:<6} {row[6]:<20} {row[7]:<6} {row[8]}")

def auto_add_scores(match_id):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT id, name FROM players
            WHERE active = 1 AND team = 'PLTE'
        """)
        players = cur.fetchall()

        for pid, name in players:
            cur.execute("""
                SELECT score, points FROM matchscore
                WHERE match_id = ? AND player_id = ?
            """, (match_id, pid))
            if cur.fetchone():
                print(f"➡️  Player {name} (ID {pid}) already has a score. Skipping.")
                continue

            while True:
                score_input = input(f"🔢 Score for {name}: ")
                if score_input.lower() == "cancel":
                    print("⛔ Aborted.")
                    return
                if score_input.lower() == "skip":
                    print(f"↪️  Skipping {name}.")
                    break
                try:
                    score = int(score_input)
                    if 0 <= score <= 75000:
                        break
                except ValueError:
                    pass
                print("❌ Invalid score. Try again.")

            if score_input.lower() == "skip":
                continue

            while True:
                points_input = input(f"⭐ Points for {name}: ")
                if points_input.lower() == "cancel":
                    print("⛔ Aborted.")
                    return
                if points_input.lower() == "skip":
                    print(f"↪️  Skipping {name}.")
                    break
                try:
                    points = int(points_input)
                    if 0 <= points <= 300:
                        break
                except ValueError:
                    pass
                print("❌ Invalid points. Try again.")

            if points_input.lower() == "skip":
                continue

            conn.execute("""
                INSERT INTO matchscore (match_id, player_id, score, points)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(match_id, player_id)
                DO UPDATE SET score = excluded.score, points = excluded.points
            """, (match_id, pid, score, points))

            print(f"✅ Saved for {name}: Score {score}, Points {points}")

def list_scores(*args):
    match_filter = None
    season_filter = None

    i = 0
    while i < len(args):
        if args[i] == "--match" and i + 1 < len(args):
            match_filter = int(args[i + 1])
            i += 2
        elif args[i] == "--season":
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                season_filter = args[i + 1]
                i += 2
            else:
                season_filter = "%"
                i += 1
        else:
            i += 1

    query = """
        SELECT ms.id, m.id, m.start, m.opponent,
               s.name, s.division, p.name, ms.score, ms.points
        FROM matchscore ms
        JOIN match m ON ms.match_id = m.id
        JOIN season s ON m.season_number = s.number
        JOIN players p ON ms.player_id = p.id
    """
    filters = []
    values = []

    if match_filter:
        filters.append("m.id = ?")
        values.append(match_filter)
    if season_filter:
        filters.append("s.name LIKE ?")
        values.append(season_filter)

    if filters:
        query += " WHERE " + " AND ".join(filters)

    query += " ORDER BY m.id DESC, ms.score DESC"

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(query, values)
        rows = cur.fetchall()

    if not rows:
        print("⚠️ No scores found.")
        return

    if match_filter:
        match_id = rows[0][1]
        match_date = rows[0][2]
        opponent = rows[0][3]
        season = rows[0][4].lstrip("S")  # z. B. "S51" → "51"
        print(f"📊 Match {match_id} – {opponent} | {match_date} | Season {season}\n")

    print(f"{'ID':<4} {'Player':<20} {'Score':<6} {'Points'}")
    print("-" * 40)
    for row in rows:
        print(f"{row[0]:<4} {row[6]:<20} {row[7]:<6} {row[8]}")


def edit_score(args):
    if not args or not args[0].isdigit():
        print("Usage: matchscore edit <id> [--score <newscore>] [--points <newpoints>]")
        return

    score_id = int(args[0])
    new_score = None
    new_points = None

    i = 1
    while i < len(args):
        if args[i] == "--score" and i + 1 < len(args):
            new_score = int(args[i + 1])
            i += 2
        elif args[i] == "--points" and i + 1 < len(args):
            new_points = int(args[i + 1])
            i += 2
        else:
            i += 1

    if new_score is None and new_points is None:
        print("⚠️ Nothing to update.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if new_score is not None:
            cur.execute("UPDATE matchscore SET score = ? WHERE id = ?", (new_score, score_id))
        if new_points is not None:
            cur.execute("UPDATE matchscore SET points = ? WHERE id = ?", (new_points, score_id))

        conn.commit()

        cur.execute("""
            SELECT ms.id, m.id, m.start, m.opponent,
                   s.name, s.division, p.name, ms.score, ms.points
            FROM matchscore ms
            JOIN match m ON ms.match_id = m.id
            JOIN season s ON m.season_number = s.number
            JOIN players p ON ms.player_id = p.id
            WHERE ms.id = ?
        """, (score_id,))
        row = cur.fetchone()

        print(f"\n✅ Score updated:")
        print(f"{'ID':<3} {'Match':<6} {'Date':<10} {'Opponent':<15} {'Season':<12} {'Div':<6} {'Player':<20} {'Score':<6} {'Points'}")
        print("-" * 100)
        print(f"{row[0]:<3} {row[1]:<6} {row[2]:<10} {row[3]:<15} {row[4]:<12} {row[5]:<6} {row[6]:<20} {row[7]:<6} {row[8]}")

