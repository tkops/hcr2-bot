import csv
import sqlite3
import subprocess
import sys
from datetime import datetime

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
    subprocess.run(cmd, check=True)

def import_matchscores():
    with sqlite3.connect(DB_PATH) as conn:
        added = 0
        skipped = 0

        with open(TSV_FILE, newline='', encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            headers = next(reader)
            header_map = {h.strip(): i for i, h in enumerate(headers)}

            for row in reader:
                try:
                    player_id = int(row[0].strip())
                    score = int(row[header_map["Score"]].strip())
                    points_raw = row[header_map.get("Points", "")].strip()
                    points = int(points_raw) if points_raw else 0
                    event = row[header_map["Event"]].strip()
                    opponent = row[header_map["Gegner"]].strip()
                    date_str = row[header_map["Datum"]].strip()
                    datetime.strptime(date_str, "%Y-%m-%d")
                except Exception as e:
                    print(f"⚠️  Skipped: Malformed row or missing data → {row}")
                    skipped += 1
                    continue

                if not player_exists(conn, player_id):
                    print(f"⚠️  Skipped: Player ID {player_id} not found.")
                    skipped += 1
                    continue

                match_id = get_match_id(conn, event, opponent, date_str)
                if not match_id:
                    print(f"⚠️  Skipped: Match not found → event='{event}', opponent='{opponent}', date={date_str}")
                    skipped += 1
                    continue

                cur = conn.cursor()
                cur.execute("""
                    SELECT 1 FROM matchscore WHERE match_id = ? AND player_id = ?
                """, (match_id, player_id))
                if cur.fetchone():
                    print(f"⚠️  Skipped: Entry already exists → match={match_id}, player={player_id}")
                    skipped += 1
                    continue

                if DO_IMPORT:
                    try:
                        run_hcr2_add(match_id, player_id, score, points)
                        added += 1
                    except subprocess.CalledProcessError:
                        print(f"❌ Failed to import: match={match_id}, player={player_id}")
                        skipped += 1
                else:
                    print(f"📝 Dry Run: match={match_id}, player={player_id}, score={score}, points={points}")
                    added += 1

        print(f"\n✅ {added} entries {'imported' if DO_IMPORT else 'simulated'}, {skipped} skipped.")

if __name__ == "__main__":
    import_matchscores()

