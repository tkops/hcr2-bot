# modules/match.py
import sqlite3
from datetime import datetime
from dateutil.relativedelta import relativedelta

DB_PATH = "db/hcr2.db"


# ----------------------------- Command Router -------------------------------

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
        edit_match(args)
    elif cmd == "show":
        if len(args) != 1 or not args[0].isdigit():
            print("Usage: match show <id>")
            return
        show_match(int(args[0]))
    elif cmd == "delete":
        if len(args) != 1 or not args[0].isdigit():
            print("Usage: match delete <id>")
            return
        delete_match(int(args[0]))
    else:
        print(f"❌ Unknown match command: {cmd}")
        print_help()


# ----------------------------- Help / Usage ---------------------------------

def print_help():
    print("Usage: python hcr2.py match <command> [args]\n")
    print("Available commands:")
    print("  add   --teamevent ID --season NUM --start YYYY-MM-DD --opponent NAME [--score N] [--scoreopp N]")
    print("  edit  --id ID [--teamevent ID] [--season NUM] [--start YYYY-MM-DD] "
          "[--opponent NAME] [--score N] [--scoreopp N]")
    print("  show  <id>")
    print("  list  [season_number|all]")
    print("  delete <id>")
    print("\nNotes:")
    print("  • --score      = Punkte ‚Ladys‘")
    print("  • --scoreopp   = Punkte Gegner")
    print("  • Reihenfolge der Schalter ist egal. --flag=value wird ebenfalls unterstützt.")


# --------------------------- Flag Parsing Utils -----------------------------

def _parse_flags(args):
    """
    Parsen von --flag value oder --flag=value.
    Gibt ein dict mit Strings zurück (ohne Typkonvertierung).
    """
    out = {}
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("--"):
            if "=" in token:
                flag, val = token.split("=", 1)
                out[flag.lstrip("-").lower()] = val
                i += 1
            else:
                flag = token.lstrip("-").lower()
                # nächster Wert, falls vorhanden und kein weiterer --flag
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    out[flag] = args[i + 1]
                    i += 2
                else:
                    # leeres Flag => setze True (für spätere evtl. bool-Flags)
                    out[flag] = "true"
                    i += 1
        else:
            # Positionsargumente sind hier nicht vorgesehen -> ignorieren
            i += 1
    return out


def _to_int(val, field_name):
    try:
        return int(val)
    except (TypeError, ValueError):
        print(f"❌ Invalid integer for '{field_name}': {val!r}")
        return None


# ------------------------------- Add Match ----------------------------------

def add_match(args):
    flags = _parse_flags(args)

    teamevent_id = _to_int(flags.get("teamevent"), "teamevent")
    season_number = _to_int(flags.get("season"), "season")
    start = flags.get("start")
    opponent = flags.get("opponent")

    score_ladys = _to_int(flags.get("score", "0"), "score")
    score_opponent = _to_int(flags.get("scoreopp", "0"), "scoreopp")

    missing = []
    if teamevent_id is None:
        missing.append("--teamevent")
    if season_number is None:
        missing.append("--season")
    if not start:
        missing.append("--start")
    if not opponent:
        missing.append("--opponent")

    if missing:
        print("Usage: match add --teamevent ID --season NUM --start YYYY-MM-DD --opponent NAME "
              "[--score N] [--scoreopp N]")
        print("Missing:", ", ".join(missing))
        return

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO match (teamevent_id, season_number, start, opponent, score_ladys, score_opponent)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (teamevent_id, season_number, start, opponent,
             score_ladys if score_ladys is not None else 0,
             score_opponent if score_opponent is not None else 0)
        )

    print(f"✅ Match added: Event {teamevent_id}, Season {season_number}, vs {opponent} on {start} "
          f"(Score Ladys: {score_ladys or 0}, Score Opponent: {score_opponent or 0})")


# ------------------------------- Edit Match ---------------------------------

def edit_match(args):
    flags = _parse_flags(args)

    mid = _to_int(flags.get("id"), "id")
    if mid is None:
        print("Usage: match edit --id ID [--teamevent ID] [--season NUM] [--start YYYY-MM-DD] "
              "[--opponent NAME] [--score N] [--scoreopp N]")
        return

    # Felder einsammeln
    set_clauses = []
    values = []

    if "teamevent" in flags:
        teamevent_id = _to_int(flags.get("teamevent"), "teamevent")
        if teamevent_id is None:
            return
        set_clauses.append("teamevent_id = ?")
        values.append(teamevent_id)

    if "season" in flags:
        season_number = _to_int(flags.get("season"), "season")
        if season_number is None:
            return
        set_clauses.append("season_number = ?")
        values.append(season_number)

    if "start" in flags:
        start = flags.get("start")
        set_clauses.append("start = ?")
        values.append(start)

    if "opponent" in flags:
        opponent = flags.get("opponent")
        set_clauses.append("opponent = ?")
        values.append(opponent)

    if "score" in flags:
        score_ladys = _to_int(flags.get("score"), "score")
        if score_ladys is None:
            return
        set_clauses.append("score_ladys = ?")
        values.append(score_ladys)

    if "scoreopp" in flags:
        score_opponent = _to_int(flags.get("scoreopp"), "scoreopp")
        if score_opponent is None:
            return
        set_clauses.append("score_opponent = ?")
        values.append(score_opponent)

    if not set_clauses:
        print("Nothing to update. Provide at least one of: "
              "--teamevent / --season / --start / --opponent / --score / --scoreopp")
        return

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE match SET {', '.join(set_clauses)} WHERE id = ?",
            (*values, mid)
        )
        if cur.rowcount == 0:
            print(f"❌ Match ID {mid} not found.")
        else:
            print(f"✏️  Match {mid} updated.")


# ------------------------------- Read/List ----------------------------------

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
        print(f"⚠️  Warning: Expected {expected} matches for {start.strftime('%B %Y')} "
              f"(Season {season_number}), but found {actual_count}.")


def delete_match(mid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM match WHERE id = ?", (mid,))
    print(f"🗑️  Match {mid} deleted.")

