import sqlite3
import yaml
import sys

DB_PATH = "db/hcr2.db"

def import_vehicles(input_file=None):
    if input_file:
        with open(input_file, "r") as f:
            vehicles = yaml.safe_load(f)
    else:
        vehicles = yaml.safe_load(sys.stdin)

    count = 0
    with sqlite3.connect(DB_PATH) as conn:
        for v in vehicles:
            try:
                conn.execute("INSERT INTO vehicle (name, shortname) VALUES (?, ?)", (v["name"], v["shortname"]))
                count += 1
            except sqlite3.IntegrityError:
                pass
    print(f"✅ Imported {count} new vehicles.")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    import_vehicles(path)

