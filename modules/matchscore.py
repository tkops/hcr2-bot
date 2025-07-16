import sqlite3
import statistics

DB_PATH = "db/hcr2.db"

def handle_command(cmd, args):
    if cmd == "avg":
        show_average()
    else:
        print(f"❌ Unknown stats command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py stats <command> [args]")
    print("\nAvailable commands:")
    print("  avg                       Show player averages for current season")

def format_k(value):
    if value >= 1000:
        return f"{round(value / 1000, 1)}k"
    return str(value)

def show_average():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        # Aktuelle Saison bestimmen
        cur.execute("SELECT MAX(number) FROM season")
        season_number = cur.fetchone()[0]
        if not season_number:
            print("⚠️ Keine Saison gefunden.")
            return

        # Alle relevanten Scores aus dieser Saison holen
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

        # Scores gruppieren nach Match-ID
        scores_by_match = {}
        for pid, name, score, match_id in rows:
            if score is None:
                continue
            scores_by_match.setdefault(match_id, []).append((pid, name, score))

        player_scores = {}
        player_names = {}

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

        # Nur aktive Spieler anzeigen
        cur.execute("SELECT id FROM players WHERE active = 1")
        active_ids = {row[0] for row in cur.fetchall()}

        print(f"\n📊 Durchschnittliche Abweichung (Saison {season_number} — 0 = Durchschnitt, positiv = besser)")
        print("-" * 70)
        print(f"{'Player':<20} {'Ø-Delta':>20}")
        print("-" * 70)

        entries = []
        for pid, deltas in player_scores.items():
            if pid not in active_ids:
                continue
            avg_delta = round(sum(deltas) / len(deltas))
            entries.append((player_names[pid], avg_delta))

        for name, delta in sorted(entries, key=lambda x: x[1], reverse=True):
            print(f"{name:<20} {format_k(delta):>20}")

