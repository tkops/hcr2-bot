import sqlite3

DB_PATH = "db/hcr2.db"

def create_tables():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            alias TEXT,
            garage_power INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS vehicle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            shortname TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS teamevent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            start TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS teamevent_vehicle (
            teamevent_id INTEGER NOT NULL,
            vehicle_id INTEGER NOT NULL,
            PRIMARY KEY (teamevent_id, vehicle_id),
            FOREIGN KEY (teamevent_id) REFERENCES teamevent(id) ON DELETE CASCADE,
            FOREIGN KEY (vehicle_id) REFERENCES vehicle(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS season (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER NOT NULL,
            name TEXT NOT NULL,
            start TEXT NOT NULL,
            division TEXT NOT NULL
        );

        """)
    print("✅ All tables created or verified.")

if __name__ == "__main__":
    create_tables()

