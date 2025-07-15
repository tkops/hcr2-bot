import sqlite3
import sys

DB_PATH = "db/hcr2.db"

def update_player(player_id, name=None, alias=None, garage_power=None, active=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if alias is not None:
        updates.append("alias = ?")
        params.append(alias)
    if garage_power is not None:
        updates.append("garage_power = ?")
        params.append(garage_power)
    if active is not None:
        updates.append("active = ?")
        params.append(1 if active else 0)

    if not updates:
        print("⚠️ Nothing to update.")
        return

    params.append(player_id)
    query = f"UPDATE players SET {', '.join(updates)} WHERE id = ?"
    cur.execute(query, tuple(params))
    conn.commit()
    conn.close()

    print(f"✅ Player {player_id} updated.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python edit_player.py <id> [--name NAME] [--alias ALIAS] [--gp GARAGE_POWER] [--active true|false]")
        sys.exit(1)

    pid = int(sys.argv[1])
    args = sys.argv[2:]

    name = None
    alias = None
    garage_power = None
    active = None

    while args:
        arg = args.pop(0)
        if arg == "--name":
            name = args.pop(0)
        elif arg == "--alias":
            alias = args.pop(0)
        elif arg == "--gp":
            garage_power = int(args.pop(0))
        elif arg == "--active":
            val = args.pop(0).lower()
            active = val == "true"

    update_player(pid, name, alias, garage_power, active)

