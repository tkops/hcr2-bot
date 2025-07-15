import sqlite3
import sys

DB_PATH = "db/hcr2.db"

def add_player(name, alias=None, garage_power=0, active=True):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO players (name, alias, garage_power, active)
        VALUES (?, ?, ?, ?)
    """, (name, alias, garage_power, int(active)))
    conn.commit()
    conn.close()
    print(f"✅ Player '{name}' added.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python add_player.py <name> [alias] [garage_power] [active]")
        sys.exit(1)

    name = sys.argv[1]
    alias = sys.argv[2] if len(sys.argv) > 2 else None
    garage_power = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    active = sys.argv[4].lower() != "false" if len(sys.argv) > 4 else True

    add_player(name, alias, garage_power, active)

