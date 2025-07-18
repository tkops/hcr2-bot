import sqlite3

DB_PATH = "db/hcr2.db"


def handle_command(cmd, args):
    if cmd == "add":
        add_teamevent(args)
    elif cmd == "list":
        list_teamevents()
    elif cmd == "delete":
        if len(args) != 1:
            print("Usage: teamevent delete <id>")
            return
        delete_teamevent(int(args[0]))
    else:
        print(f"❌ Unknown teamevent command: {cmd}")
        print_help()


def print_help():
    print("Usage: python hcr2.py teamevent <command> [args]")
    print("\nAvailable commands:")
    print("  add <name> <start-date> <vehicle_ids>")
    print("  list")
    print("  delete <id>")


def add_teamevent(args):
    if len(args) < 3:
        print("Usage: teamevent add <name> <start-date> <vehicle_ids>")
        return

    name = args[0]
    start = args[1]
    vehicle_ids = [int(v.strip())
                   for v in args[2].split(",") if v.strip().isdigit()]

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO teamevent (name, start) VALUES (?, ?)", (name, start))
        teamevent_id = cur.lastrowid

        for vid in vehicle_ids:
            try:
                cur.execute(
                    "INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (?, ?)",
                    (teamevent_id, vid)
                )
            except sqlite3.IntegrityError:
                print(
                    f"⚠️  Vehicle ID {vid} does not exist or is already linked.")

    print(f"✅ Teamevent '{name}' created with vehicles: {vehicle_ids}")


def list_teamevents():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, start FROM teamevent ORDER BY start DESC")
        events = cur.fetchall()

        print(f"{'ID.':>4} {'Start':<10}  {'Name':<25}  {'Vehicles'}")
        print("-" * 130)

        for eid, name, start in events:
            cur.execute("""
                SELECT v.id, v.name
                FROM teamevent_vehicle tv
                JOIN vehicle v ON tv.vehicle_id = v.id
                WHERE tv.teamevent_id = ?
                ORDER BY v.id
            """, (eid,))
            vehicles = cur.fetchall()
            vstr = ", ".join(f"{vid}:{vname}" for vid, vname in vehicles) if vehicles else "-"
            print(f"{eid:>3}. {start:<10}  {name:<25}  {vstr}")


def delete_teamevent(eid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (eid,))
        conn.execute("DELETE FROM teamevent WHERE id = ?", (eid,))
    print(f"🗑️  Teamevent {eid} deleted.")
