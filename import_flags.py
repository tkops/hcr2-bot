import sqlite3
import requests

DB_PATH = "../hcr2-db/hcr2.db"
JSON_URL = "https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-Regional-Codes/master/all/all.json"

def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flags (
            alpha2 TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
    """)

def import_flags():
    print("⬇️  Downloading country data ...")
    resp = requests.get(JSON_URL)
    resp.raise_for_status()
    data = resp.json()

    with sqlite3.connect(DB_PATH) as conn:
        ensure_table(conn)
        cur = conn.cursor()

        inserted = 0
        updated = 0

        for entry in data:
            code = entry.get("alpha-2")
            name = entry.get("name")

            if not code or not name:
                continue

            cur.execute("SELECT name FROM flags WHERE alpha2 = ?", (code,))
            row = cur.fetchone()

            if row:
                if row[0] != name:
                    cur.execute("UPDATE flags SET name = ? WHERE alpha2 = ?", (name, code))
                    updated += 1
            else:
                cur.execute("INSERT INTO flags (alpha2, name) VALUES (?, ?)", (code, name))
                inserted += 1

        conn.commit()

    print(f"✅ Done. {inserted} inserted, {updated} updated.")

if __name__ == "__main__":
    import_flags()

