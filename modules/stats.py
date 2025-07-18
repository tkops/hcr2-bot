import sqlite3
import statistics
import datetime
import sys

DB_PATH = "db/hcr2.db"

def handle_command(cmd, args):
    if cmd == "avg":
        season_arg = int(args[0]) if args else None
        show_average(season_arg)
    elif cmd == "alias":
        show_plte_alias()
    else:
        print(f"❌ Unknown stats command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py stats <command> [args]")
    print("\nAvailable commands:")
    print("  avg [season]              Show player averages for current or given season")
    print("  alias                     Show alias of active players in plte team sorted by rank")

def format_k(value):
    abs_val = abs(value)
    if abs_val >= 100:
        return f"{'-' if value < 0 else ''}{round(abs_val / 1000, 1)}k"
    else:
        return f"{'-' if value < 0 else ''}0.0k"

def find_current_season(cur):
    today = datetime.date.today().isoformat()
    cur.execute("SELECT number FROM season WHERE start <= ? ORDER BY start DESC LIMIT 1", (today,))
    row = cur.fetchone()
    return row[0] if row else None

def show_average(season_number=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if season_number is None:
            season_number = find_current_season(cur)

        if not season_number:
            print("⚠️ Keine passende Saison gefunden.")
            return

        cur.execute("""
            SELECT
                ms.player_id,
                p.name,
                ms.score,
                m.id
            FROM matchscore ms
            JOIN players p ON ms.player_id = p.id
            JOIN match m ON ms.match_id = m.id
            WHERE m.season_number = ?
        """, (season_number,))
        rows = cur.fetchall()

        if not rows:
            print("⚠️ Keine Matchscores gefunden.")
            return

        scores_by_match = {}
        for pid, name, score, match_id in rows:
            if score is None:
                continue
            scores_by_match.setdefault(match_id, []).append((pid, name, score))

        player_scores = {}
        player_names = {}
        player_counts = {}

        for match_id, entries in scores_by_match.items():
            scores = [score for _, _, score in entries]
            if not scores:
                continue
            try:
                median = statistics.median(scores)
            except statistics.StatisticsError:
                continue
            for pid, name, score in entries:
                delta = score - median
                player_scores.setdefault(pid, []).append(delta)
                player_names[pid] = name
                player_counts[pid] = player_counts.get(pid, 0) + 1

        cur.execute("SELECT id FROM players WHERE active = 1")
        active_ids = {row[0] for row in cur.fetchall()}

        entries = []
        for pid, deltas in player_scores.items():
            if pid not in active_ids:
                continue
            avg_delta = round(sum(deltas) / len(deltas))
            count = player_counts.get(pid, 0)
            entries.append((player_names[pid], avg_delta, count))
        
        print(f"{'#':>2}   {'Lady':<14} {'Perf':>6} {'Mat.':<2}")
        print("-" * 31)

        for i, (name, delta, count) in enumerate(sorted(entries, key=lambda x: x[1], reverse=True), 1):
            if i > 50:
                break
            print(f"{i:>2}.  {name:<14} {format_k(delta):>6} {count:>2}")
def show_plte_alias():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        season_number = find_current_season(cur)
        if not season_number:
            return

        cur.execute("""
            SELECT
                ms.player_id,
                p.alias,
                ms.score,
                m.id,
                p.team
            FROM matchscore ms
            JOIN players p ON ms.player_id = p.id
            JOIN match m ON ms.match_id = m.id
            WHERE m.season_number = ?
        """, (season_number,))
        rows = cur.fetchall()

        if not rows:
            return

        scores_by_match = {}
        for pid, alias, score, match_id, team in rows:
            if score is None:
                continue
            scores_by_match.setdefault(match_id, []).append((pid, alias, score, team))

        player_scores = {}
        player_alias = {}
        player_counts = {}

        for match_id, entries in scores_by_match.items():
            scores = [score for _, _, score, _ in entries]
            if not scores:
                continue
            try:
                median = statistics.median(scores)
            except statistics.StatisticsError:
                continue
            for pid, alias, score, team in entries:
                if team != "PLTE":
                    continue
                delta = score - median
                player_scores.setdefault(pid, []).append(delta)
                player_alias[pid] = alias
                player_counts[pid] = player_counts.get(pid, 0) + 1

        cur.execute("SELECT id FROM players WHERE active = 1 AND team = 'PLTE'")
        active_ids = {row[0] for row in cur.fetchall()}

        entries = []
        for pid, deltas in player_scores.items():
            if pid not in active_ids:
                continue
            avg_delta = round(sum(deltas) / len(deltas))
            entries.append((player_alias[pid], avg_delta))

        for alias, _ in sorted(entries, key=lambda x: x[1], reverse=True):
            print(alias)
