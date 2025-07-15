import sqlite3
import sys

DB_PATH = "db/hcr2.db"

def list_players(active_filter=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    base_query = """
        SELECT id, name, alias, garage_power, active, created_at
        FROM players
    """

    params = ()
    if active_filter is not None:
        base_query += " WHERE active = ?"
        params = (1 if active_filter else 0,)

    base_query += " ORDER BY name COLLATE NOCASE"
    cur.execute(base_query, params)
    rows = cur.fetchall()
    conn.close()

    print(f"{'ID':<3} {'Name':<20} {'Alias':<15} {'GP':>6} {'Active':<6} {'Created'}")
    print("-" * 65)
    for row in rows:
        id, name, alias, gp, active, created = row
        print(f"{id:<3} {name:<20} {alias or '':<15} {gp:>6} {str(bool(active)):>6} {created}")

if __name__ == "__main__":
    active_arg = None
    if len(sys.argv) > 1:
        if sys.argv[1].lower() == "--active":
            active_arg = True
        elif sys.argv[1].lower() == "--inactive":
            active_arg = False

    list_players(active_filter=active_arg)

