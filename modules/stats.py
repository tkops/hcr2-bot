import sqlite3
import statistics

DB_PATH = "db/hcr2.db"

def handle_command(cmd, args):
    if cmd == "avg":
        season = None
        if args and args[0].isdigit():
            season = int(args[0])
        show_avg_scores(season)
    else:
        print(f"❌ Unknown stats command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py stats <command> [args]")
    print("\nAvailable commands:")
    print("  avg [season]    Show average median-relative scores per player")

def show_avg_scores(season=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if not season:
            cur.execute("SELECT MAX(number) FROM season")
            result = cur.fetchone()
            if result and result[0]:
                season = result[0]
            else:
                print("⚠️ No season found.")
                return

        # Aktive Spieler laden
        cur.execute("SELECT id, name FROM players WHERE active = 1")
        active_players = {pid: name for pid, name in cur.fetchall()}

        # Matchdaten und Scores abrufen
        cur.execute("""
            SELECT
                ms.player_id,
                ms.score,
                m.id as match_id
            FROM matchscore ms
            JOIN match m ON ms.match_id = m.id
            WHERE m.season_number = ?
        """, (season,))

        data = cur.fetchall()

        if not data:
            print("❌ Keine Scores gefunden.")
            return

        # Scores pro Match sammeln
        match_scores = {}
        for pid, score, mid in data:
            match_scores.setdefault(mid, []).append((pid, score))

        player_deltas = {pid: [] for pid in active_players}

        for match_id, entries in match_scores.items():
            scores = [score for _, score in entries]
            if not scores:
                continue
            median = statistics.median(scores)
            for pid, score in entries:
                if pid in player_deltas:
                    delta = score - median
                    player_deltas[pid].append(delta)

        # Durchschnittliche Abweichungen berechnen
        player_avg = []
        for pid, deltas in player_deltas.items():
            if deltas:
                avg = round(sum(deltas) / len(deltas), 1)
                player_avg.append((active_players[pid], avg, len(deltas)))

        if not player_avg:
            print("❌ Keine gültigen Scores für aktive Spieler.")
            return

        # Nach Durchschnitt absteigend sortieren
        player_avg.sort(key=lambda x: x[1], reverse=True)

        print(f"📊 Durchschnittliche Abweichung vom Median (Season {season})")
        print(f"{'#':<3} {'Player':<20} {'ØDelta':>8} {'Matches'}")
        print("-" * 40)
        for i, (name, avg, count) in enumerate(player_avg, 1):
            print(f"{i:<3} {name:<20} {avg:>8} {count}")

