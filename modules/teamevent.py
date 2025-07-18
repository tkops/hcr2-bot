import sqlite3

DB_PATH = "db/hcr2.db"


def handle_command(cmd, args):
    if cmd == "add":
        add_teamevent(args)
    elif cmd == "list":
        list_teamevents()
    elif cmd == "edit":
        edit_teamevent(args)
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
    print("  add <name> <start-date> <vehicle_ids> [--tracks 4|5]")
    print("  list")
    print("  edit <id> [--name NAME] [--start DATE] [--tracks 4|5] [--vehicles id1,id2,...]")
    print("  delete <id>")


def add_teamevent(args):
    if len(args) < 3:
        print("Usage: teamevent add <name> <start-date> <vehicle_ids> [--tracks 4|5]")
        return

    name = args[0]
    start = args[1]
    vehicle_ids = [int(v.strip()) for v in args[2].split(",") if v.strip().isdigit()]
    tracks = 4

    # Optional: --tracks 5
    if "--tracks" in args:
        idx = args.index("--tracks")
        if len(args) > idx + 1 and args[idx + 1].isdigit():
            tracks = int(args[idx + 1])
            if tracks not in (4, 5):
                print("❌ Tracks must be 4 or 5.")
                return

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO teamevent (name, start, tracks) VALUES (?, ?, ?)",
            (name, start, tracks)
        )
        teamevent_id = cur.lastrowid

        for vid in vehicle_ids:
            try:
                cur.execute(
                    "INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (?, ?)",
                    (teamevent_id, vid)
                )
            except sqlite3.IntegrityError:
                print(f"⚠️  Vehicle ID {vid} does not exist or is already linked.")

    print(f"✅ Teamevent '{name}' created with {tracks} tracks and vehicles: {vehicle_ids}")


def list_teamevents():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, start, tracks FROM teamevent ORDER BY start DESC")
        events = cur.fetchall()

        print(f"{'ID.':>4} {'Start':<10}  {'Tracks':<6}  {'Name':<25}  {'Vehicles'}")
        print("-" * 130)

        for eid, name, start, tracks in events:
            cur.execute("""
                SELECT v.id, v.name
                FROM teamevent_vehicle tv
                JOIN vehicle v ON tv.vehicle_id = v.id
                WHERE tv.teamevent_id = ?
                ORDER BY v.id
            """, (eid,))
            vehicles = cur.fetchall()
            vstr = ", ".join(f"{vid}:{vname}" for vid, vname in vehicles) if vehicles else "-"
            print(f"{eid:>3}. {start:<10}  {str(tracks):<6}  {name:<25}  {vstr}")


def edit_teamevent(args):
    if len(args) < 1:
        print("Usage: teamevent edit <id> [--name NAME] [--start DATE] [--tracks 4|5] [--vehicles id1,id2,...]")
        return

    eid = int(args[0])
    name = start = tracks = None
    vehicle_ids = None

    i = 1
    while i < len(args):
        if args[i] == "--name":
            i += 1
            name = args[i]
        elif args[i] == "--start":
            i += 1
            start = args[i]
        elif args[i] == "--tracks":
            i += 1
            if args[i].isdigit() and int(args[i]) in (4, 5):
                tracks = int(args[i])
            else:
                print("❌ Tracks must be 4 or 5.")
                return
        elif args[i] == "--vehicles":
            i += 1
            vehicle_ids = [int(v.strip()) for v in args[i].split(",") if v.strip().isdigit()]
        i += 1

    if not any([name, start, tracks, vehicle_ids]):
        print("⚠️  Nothing to update.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        fields = []
        values = []

        if name:
            fields.append("name = ?")
            values.append(name)
        if start:
            fields.append("start = ?")
            values.append(start)
        if tracks is not None:
            fields.append("tracks = ?")
            values.append(tracks)

        if fields:
            query = f"UPDATE teamevent SET {', '.join(fields)} WHERE id = ?"
            values.append(eid)
            cur.execute(query, values)

        if vehicle_ids is not None:
            # Clear old assignments
            cur.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (eid,))
            for vid in vehicle_ids:
                try:
                    cur.execute(
                        "INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (?, ?)",
                        (eid, vid)
                    )
                except sqlite3.IntegrityError:
                    print(f"⚠️  Vehicle ID {vid} does not exist or is already linked.")

    print(f"✅ Teamevent {eid} updated.")


def delete_teamevent(eid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (eid,))
        conn.execute("DELETE FROM teamevent WHERE id = ?", (eid,))
    print(f"🗑️  Teamevent {eid} deleted.")

