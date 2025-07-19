import sqlite3

DB_PATH = "db/hcr2.db"
SCHEMA_FILE = "schema.sql"


def create_tables():
    with open(SCHEMA_FILE, "r") as f:
        schema_sql = f.read()

    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema_sql)

    print(f"✅ Tables created from {SCHEMA_FILE}")


if __name__ == "__main__":
    create_tables()

