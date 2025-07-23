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
                SELECT m.id, m.start, m.season_number, m.opponent, t.name, m.score_ladys, m.score_opponent
                FROM match m
                JOIN teamevent t ON m.teamevent_id = t.id
                ORDER BY m.start DESC
            """)
            matches = cur.fetchall()
        else:
            if season_number is None:
                season_number = get_current_season_number()
            cur.execute("""
                SELECT m.id, m.start, m.season_number, m.opponent, t.name, m.score_ladys, m.score_opponent
                FROM match m
                JOIN teamevent t ON m.teamevent_id = t.id
                WHERE m.season_number = ?
                ORDER BY m.start DESC
            """, (season_number,))
            matches = cur.fetchall()

    print(f"{'ID':<5} {'Start':<12} {'Season':<8} {'Opponent':<25} {'Event':<30} {'Ladys':>6} {'Opp.':>6}")
    print("-" * 100)
    for mid, start, season, opp, event_name, s_ladys, s_opp in matches:
        print(f"{mid:>5}. {start:<12} S{season:<7} {opp:<25} {event_name:<30} {s_ladys:>6} {s_opp:>6}")

    if not all_seasons:
        print(f"\n📊 {len(matches)} matches in Season {season_number}")
        warn_if_unusual_match_count(season_number, len(matches))


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

