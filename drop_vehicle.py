import sqlite3

DB_PATH = "db/hcr2.db"

def drop_vehicle_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS vehicle;")
    print("🗑️  'vehicle' table has been dropped.")

if __name__ == "__main__":
    drop_vehicle_table()

