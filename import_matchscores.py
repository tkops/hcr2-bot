import csv
import sqlite3
import subprocess
import sys
from datetime import datetime
from collections import Counter, defaultdict

DB_PATH = "db/hcr2.db"
TSV_FILE = "all.tsv"
HCR2_CLI = "python hcr2.py"
DO_IMPORT = "--import" in sys.argv


def get_match_id(conn, event, opponent, date_str):
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id
        FROM match m
        JOIN teamevent t ON m.teamevent_id = t.id
        WHERE t.name = ? AND m.opponent = ? AND m.start = ?
    """, (event, opponent, date_str))
    row = cur.fetchone()
    return row[0] if row else None


def player_exists(conn, player_id):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM players WHERE id = ?", (player_id,))
    return cur.fetchone() is not None


def run_hcr2_add(match_id, player_id, score, points):
    cmd = [*HCR2_CLI.split(), "matchscore", "add", str(match_id), str(player_id), str(score), str(points)]
    subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.DEVNULL,  # CHANGED/UNCHANGED unterdrücken
        stderr=subprocess.DEVNULL,
        text=True,
    )


def import_matchscores():
    with sqlite3.connect(DB_PATH) as conn:
        counts = Counter()

        # Detailsammlungen
        import_failed_details = []  # echte Importfehler beim DO_IMPORT
        match_missing_keys = defaultdict(int)  # (event, opponent, date) -> count

        with open(TSV_FILE, newline='', encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            headers = next(reader)
            header_map = {h.strip(): i for i, h in enumerate(headers)}

            for row in reader:
                # 1) Parsen/Validieren
                try:
                    player_id = int(row[0].strip())
                    score = int(row[header_map["Score"]].strip())
                    if "Points" in header_map and row[header_map["Points"]].strip():
                        points = int(row[header_map["Points"]].strip())
                    else:
                        points = 0
                    event = row[header_map["Event"]].strip()
                    opponent = row[header_map["Gegner"]].strip()
                    date_str = row[header_map["Datum"]].strip()
                    datetime.strptime(date_str, "%Y-%m-%d")
                except Exception:
                    counts["malformed"] += 1
                    continue

                # 2) Checks in DB
                if not player_exists(conn, player_id):
                    counts["player_missing"] += 1
                    continue

                match_id = get_match_id(conn, event, opponent, date_str)
                if not match_id:
                    counts["match_missing"] += 1
                    match_missing_keys[(event, opponent, date_str)] += 1
                    continue

                cur = conn.cursor()
                cur.execute("SELECT 1 FROM matchscore WHERE match_id = ? AND player_id = ?", (match_id, player_id))
                if cur.fetchone():
                    counts["duplicate"] += 1
                    continue

                # 3) Import / Dry Run
                if DO_IMPORT:
                    try:
                        run_hcr2_add(match_id, player_id, score, points)
                        counts["imported"] += 1
                    except subprocess.CalledProcessError:
                        counts["import_failed"] += 1
                        import_failed_details.append({
                            "match_id": match_id,
                            "player_id": player_id,
                            "score": score,
                            "points": points,
                            "event": event,
                            "opponent": opponent,
                            "date": date_str,
                        })
                else:
                    counts["simulated"] += 1

        # --- Zusammenfassung ---
        mode = "imported" if DO_IMPORT else "simulated"
        total_done = counts["imported"] if DO_IMPORT else counts["simulated"]
        total_skipped = (
            counts["malformed"]
            + counts["player_missing"]
            + counts["match_missing"]
            + counts["duplicate"]
            + (counts["import_failed"] if DO_IMPORT else 0)
        )

        print(f"\n✅ {total_done} entries {mode}, {total_skipped} skipped.")

        def line(name, key):
            if counts[key]:
                print(f"  - {name}: {counts[key]}")

        print("➡️  Skips by reason:")
        line("Malformed row / missing data", "malformed")
        line("Player not found", "player_missing")
        line("Match not found", "match_missing")
        line("Duplicate (already exists)", "duplicate")
        if DO_IMPORT:
            line("Import failed (subprocess)", "import_failed")

        # --- Nur noch kompakte Anzeige für 'Match not found' ---
        if match_missing_keys:
            print("\n❓ Match not found (grouped):")
            # sortiert nach Datum, Event, Opponent – optional
            for (event, opponent, date_str), cnt in sorted(match_missing_keys.items(), key=lambda x: (x[0][2], x[0][0], x[0][1])):
                print(f"  {date_str} | event='{event}' | opponent='{opponent}'  ×{cnt}")

        # --- Echte Importfehler weiterhin detailliert (selten) ---
        if DO_IMPORT and import_failed_details:
            print("\n❌ Import failed entries (details):")
            for e in import_failed_details:
                print(f"  match={e['match_id']} | player={e['player_id']} | "
                      f"score={e['score']} | points={e['points']} | "
                      f"event='{e['event']}' | opponent='{e['opponent']}' | date={e['date']}")

if __name__ == "__main__":
    import_matchscores()

