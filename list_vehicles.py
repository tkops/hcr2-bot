import sqlite3

DB_PATH = "db/hcr2.db"

def list_vehicles():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, shortname FROM vehicle ORDER BY id")
        rows = cur.fetchall()

    print(f"{'ID':<3} {'Name':<20} {'Shortname'}")
    print("-" * 35)
    for vid, name, short in rows:
        print(f"{vid:<3} {name:<20} {short}")

if __name__ == "__main__":
    list_vehicles()

