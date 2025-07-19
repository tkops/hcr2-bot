import sqlite3

DB_PATH = "db/hcr2.db"
SCHEMA_OUTPUT = "schema.sql"

def backup_schema():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = cur.fetchall()

        with open(SCHEMA_OUTPUT, "w") as f:
            for name, sql in tables:
                if not sql:
                    continue
                # Ersetze "CREATE TABLE ..." durch "CREATE TABLE IF NOT EXISTS ..."
                modified_sql = sql.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
                f.write(modified_sql.strip() + ";\n\n")

    print(f"✅ Schema saved to {SCHEMA_OUTPUT}")

if __name__ == "__main__":
    backup_schema()

