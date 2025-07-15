import sqlite3
import yaml
import sys

DB_PATH = "db/hcr2.db"

def export_vehicles(output_file=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name, shortname FROM vehicle ORDER BY name COLLATE NOCASE")
        vehicles = [{"name": name, "shortname": short} for name, short in cur.fetchall()]

    if output_file:
        with open(output_file, "w") as f:
            yaml.dump(vehicles, f, sort_keys=False, allow_unicode=True)
        print(f"✅ Exported {len(vehicles)} vehicles to '{output_file}'.")
    else:
        print(yaml.dump(vehicles, sort_keys=False, allow_unicode=True))

if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else None
    export_vehicles(output)

