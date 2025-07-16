import sqlite3
import statistics
import datetime
import sys

DB_PATH = "db/hcr2.db"

def handle_command(cmd, args):
    if cmd == "avg":
        season_arg = int(args[0]) if args else None
        show_average(season_arg)
    else:
        print(f"❌ Unknown stats command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py stats <command> [args]")
    print("\nAvailable commands:")
    print("  avg [season]              Show player averages for current or given season")

def format_k(value):
    abs_val = abs(value)
    if abs_val >= 1000:
        return f"{'-' if value < 0 else ''}{round(abs_val / 1000, 1)}k"
    return str(value)

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

        print(f"\n📊 Durchschnittliche Abweichung (Saison {season_number} — 0 = Durchschnitt, positiv = besser)")
        print("-" * 70)
        print(f"{'Player':<30} {'Ø-Delta':>10} {'Matches':>10}")
        print("-" * 70)

        entries = []
        for pid, deltas in player_scores.items():
            if pid not in active_ids:
                continue
            avg_delta = round(sum(deltas) / len(deltas))
            count = player_counts.get(pid, 0)
            entries.append((player_names[pid], avg_delta, count))

        for name, delta, count in sorted(entries, key=lambda x: x[1], reverse=True):
            print(f"{name:<30} {format_k(delta):>10} {count:>10}")

