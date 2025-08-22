import sqlite3
import sys

DB_PATH = "../hcr2-db/hcr2.db"
TSV_FILE = "all.tsv"

def import_players(do_import=False):
    seen = {}

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        with open(TSV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 2:
                    continue

                try:
                    pid = int(parts[0])
                    name = parts[1].strip()
                except ValueError:
                    continue

                # check for name mismatch
                if pid in seen:
                    if seen[pid] != name:
                        print(f"❌ ID {pid} has conflicting names: '{seen[pid]}' vs '{name}'")
                    continue
                seen[pid] = name

                cur.execute("SELECT 1 FROM players WHERE id = ?", (pid,))
                if cur.fetchone():
                    print(f"⚠️  Player {pid} already exists. Skipped.")
                    continue

                print(f"{'✅' if do_import else '🟡'} {'Importing' if do_import else 'Would import'} player {pid}: {name}")

                if do_import:
                    cur.execute("""
                        INSERT INTO players (id, name, alias, garage_power, active, birthday, team, discord_name)
                        VALUES (?, ?, NULL, 0, 0, NULL, NULL, NULL)
                    """, (pid, name))

        if do_import:
            conn.commit()

if __name__ == "__main__":
    import_players(do_import="--import" in sys.argv)

