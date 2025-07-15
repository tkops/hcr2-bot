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
        """)
    print("✅ All tables created or verified.")

if __name__ == "__main__":
    create_tables()

