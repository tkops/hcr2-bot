import sqlite3
import yaml
import sys
import os

DB_PATH = "../hcr2-db/hcr2.db"


def handle_command(cmd, args):
    if cmd == "list":
        list_vehicles()
    elif cmd == "add":
        if len(args) != 2:
            print("Usage: vehicle add <name> <shortname>")
            return
        add_vehicle(args[0], args[1])
    elif cmd == "edit":
        edit_vehicle(args)
    elif cmd == "delete":
        if len(args) != 1:
            print("Usage: vehicle delete <id>")
            return
        delete_vehicle(int(args[0]))
    elif cmd == "import":
        import_vehicles(args[0] if args else None)
    elif cmd == "export":
        export_vehicles(args[0] if args else None)
    elif cmd == "drop":
        drop_table()
    else:
        print(f"❌ Unknown vehicle command: {cmd}")


def list_vehicles():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, shortname FROM vehicle ORDER BY id")
        rows = cur.fetchall()
    print(f"{'ID':<2}   {'Name':<18} {'SN'}")
    print("-" * 26)
    for vid, name, short in rows:
        print(f"{vid:>2}.  {name:<18} {short}")


def add_vehicle(name, shortname):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO vehicle (name, shortname) VALUES (?, ?)", (name, shortname))
    print(f"✅ Added vehicle '{name}' as '{shortname}'.")


def edit_vehicle(args):
    if len(args) < 1:
        print("Usage: vehicle edit <id> [--name NAME] [--short SHORTNAME]")
        return

    vehicle_id = int(args[0])
    name = None
    short = None
    i = 1
    while i < len(args):
        if args[i] == "--name":
            i += 1
            name = args[i]
        elif args[i] == "--short":
            i += 1
            short = args[i]
        i += 1

    if not name and not short:
        print("⚠️  Nothing to update.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        fields = []
        values = []
        if name:
            fields.append("name = ?")
            values.append(name)
        if short:
            fields.append("shortname = ?")
            values.append(short)
        values.append(vehicle_id)
        conn.execute(
            f"UPDATE vehicle SET {', '.join(fields)} WHERE id = ?", values)

    print(f"✅ Vehicle {vehicle_id} updated.")


def delete_vehicle(vid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM vehicle WHERE id = ?", (vid,))
    print(f"🗑️  Vehicle {vid} deleted.")


def import_vehicles(file):
    if not file or not os.path.exists(file):
        print(f"❌ File not found: {file}")
        return

    with open(file, "r") as f:
        data = yaml.safe_load(f)

    count = 0
    with sqlite3.connect(DB_PATH) as conn:
        for v in data:
            try:
                conn.execute(
                    "INSERT INTO vehicle (name, shortname) VALUES (?, ?)", (v["name"], v["shortname"]))
                count += 1
            except sqlite3.IntegrityError:
                pass
    print(f"✅ Imported {count} new vehicles.")


def export_vehicles(file=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT name, shortname FROM vehicle ORDER BY name COLLATE NOCASE")
        data = [{"name": n, "shortname": s} for n, s in cur.fetchall()]

    yaml_str = yaml.dump(data, sort_keys=False, allow_unicode=True)
    if file:
        with open(file, "w") as f:
            f.write(yaml_str)
        print(f"✅ Exported {len(data)} vehicles to '{file}'.")
    else:
        print(yaml_str)


def drop_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS vehicle;")
    print("🗑️  Vehicle table dropped.")


def print_help():
    print("Usage: python hcr2.py vehicle <command> [args]")
    print("\nAvailable commands:")
    print("  list                  Show all vehicles")
    print("  add <name> <short>    Add new vehicle")
    print("  edit <id> [...]       Edit vehicle (e.g. --name ...)")
    print("  delete <id>           Delete vehicle by ID")
    print("  import <file>         Import from YAML file")
    print("  export [file]         Export to YAML or stdout")
    print("  drop                  Drop (delete) the entire vehicle table")
