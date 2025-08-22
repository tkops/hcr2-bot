#!/usr/bin/env python3
import sqlite3
from pathlib import Path
import sys
import difflib

DB_PATH = "../hcr2-db/hcr2.db"
SCHEMA_FILE = "schema.sql"

def dump_schema(conn):
    """Gibt alle Objekte aus sqlite_master zurück (ohne sqlite_ interne)."""
    cur = conn.cursor()
    cur.execute("""
        SELECT type, name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
    """)
    return [(t, n, (sql or "").strip()) for t, n, sql in cur.fetchall()]

def create_db():
    schema = Path(SCHEMA_FILE).read_text(encoding="utf-8")
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys=OFF;")

            # altes Schema sichern
            before = dump_schema(conn)

            # ausführen
            conn.executescript(schema)

            # neues Schema sichern
            after = dump_schema(conn)

            conn.execute("PRAGMA foreign_keys=ON;")

        # Vergleichen
        if before == after:
            print("ℹ️  No changes applied – database already up to date.")
        else:
            print("✅ Schema updated from", SCHEMA_FILE)
            # Unterschiede anzeigen (nur SQL-Vergleich)
            before_sql = [s for _, _, s in before]
            after_sql  = [s for _, _, s in after]
            diff = difflib.unified_diff(before_sql, after_sql,
                                        fromfile="before", tofile="after", lineterm="")
            for line in diff:
                print(line)

    except sqlite3.Error as e:
        print(f"❌ SQLite error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    create_db()

