import sqlite3
from datetime import datetime
from dateutil.relativedelta import relativedelta

DB_PATH = "db/hcr2.db"


def handle_command(cmd, args):
    if cmd == "add":
        add_match(args)
    elif cmd == "list":
        if args and args[0] == "all":
            list_matches(all_seasons=True)
        elif args:
            list_matches(season_number=int(args[0]))
        else:
            list_matches()  # current season
    elif cmd == "edit":
        if len(args) != 8:
            print("Usage: match edit <id> <teamevent_id> <season_number> <start> <opponent> <score_ladys> <score_opponent>")
            return
        edit_match(args)

    elif cmd == "show":
        if len(args) != 1 or not args[0].isdigit():
            print("Usage: match show <id>")
            return
        show_match(int(args[0]))

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
    print("  add <teamevent_id> <season_number> <start> <opponent> [<score_ladys> <score_opponent>]")
    print("  edit <id> <teamevent_id> <season_number> <start> <opponent> <score_ladys> <score_opponent>")
    print("  show <id>")
    print("  list [season_number|all]")
    print("  delete <id>")


def add_match(args):
    if len(args) < 4:
        print("Usage: match add <teamevent_id> <season_number> <start> <opponent> [<score_ladys> <score_opponent>]")
        return

    teamevent_id = int(args[0])
    season_number = int(args[1])
    start = args[2]
    opponent = args[3]
    score_ladys = int(args[4]) if len(args) > 4 else 0
    score_opponent = int(args[5]) if len(args) > 5 else 0

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO match (teamevent_id, season_number, start, opponent, score_ladys, score_opponent)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (teamevent_id, season_number, start, opponent, score_ladys, score_opponent)
        )

    print(f"✅ Match added: Event {teamevent_id}, Season {season_number}, vs {opponent} on {start} "
          f"(Score Ladys: {score_ladys}, Score Opponent: {score_opponent})")


def edit_match(args):
    mid = int(args[0])
    teamevent_id = int(args[1])
    season_number = int(args[2])
    start = args[3]
    opponent = args[4]
    score_ladys = int(args[5])
    score_opponent = int(args[6])

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE match
            SET teamevent_id = ?, season_number = ?, start = ?, opponent = ?, score_ladys = ?, score_opponent = ?
            WHERE id = ?
        """, (teamevent_id, season_number, start, opponent, score_ladys, score_opponent, mid))

        if cur.rowcount == 0:
            print(f"❌ Match ID {mid} not found.")
        else:
            print(f"✏️  Match {mid} updated.")


def get_current_season_number():
    base = datetime(2021, 5, 1)
    today = datetime.today()
    delta = relativedelta(today, base)
    return delta.years * 12 + delta.months + 1


def list_matches(season_number=None, all_seasons=False):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        if all_seasons:
            cur.execute("""
                SELECT m.id, m.start, t.name, m.opponent
                FROM match m
                JOIN teamevent t ON m.teamevent_id = t.id
                ORDER BY m.start DESC
            """)
            matches = cur.fetchall()
        else:
            if season_number is None:
                season_number = get_current_season_number()
            cur.execute("""
                SELECT m.id, m.start, t.name, m.opponent
                FROM match m
                JOIN teamevent t ON m.teamevent_id = t.id
                WHERE m.season_number = ?
                ORDER BY m.start DESC
            """, (season_number,))
            matches = cur.fetchall()

    print(f"{'ID':<5} {'Start':<12} {'Event':<30} {'Opponent':<20}")
    print("-" * 75)
    for mid, start, event_name, opp in matches:
        print(f"{mid:<5} {start:<12} {event_name:<30} {opp:<20}")

    if not all_seasons:
        print(f"\n📊 {len(matches)} matches in Season {season_number}")


def show_match(mid):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT m.id, m.start, m.season_number, m.opponent, t.name, m.score_ladys, m.score_opponent
            FROM match m
            JOIN teamevent t ON m.teamevent_id = t.id
            WHERE m.id = ?
        """, (mid,))
        row = cur.fetchone()

    if not row:
        print(f"❌ Match ID {mid} not found.")
        return

    match_id, start, season, opponent, event_name, score_ladys, score_opp = row
    print(f"📅 Match {match_id}")
    print(f"  Start:       {start}")
    print(f"  Season:      {season}")
    print(f"  Event:       {event_name}")
    print(f"  Opponent:    {opponent}")
    print(f"  Score Ladys: {score_ladys}")
    print(f"  Score Opp.:  {score_opp}")


def warn_if_unusual_match_count(season_number, actual_count):
    start = datetime(2021, 5, 1) + relativedelta(months=season_number - 1)
    month = start.month
    year = start.year

    if month == 2:
        expected = 13
    elif month in [4, 6, 9, 11]:
        expected = 14
    else:
        expected = 15

    if actual_count != expected:
        print(f"⚠️  Warning: Expected {expected} matches for {start.strftime('%B %Y')} (Season {season_number}), but found {actual_count}.")


def delete_match(mid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM match WHERE id = ?", (mid,))
    print(f"🗑️  Match {mid} deleted.")

