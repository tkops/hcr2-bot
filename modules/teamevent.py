import sqlite3
from datetime import datetime

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
    elif cmd == "show":
        show_teamevent(args)
    else:
        print(f"❌ Unknown teamevent command: {cmd}")
        print_help()


def print_help():
    print("Usage: python hcr2.py teamevent <command> [args]")
    print("\nAvailable commands:")
    print('  add "<name>" <Jahr>/<KW> [vehicle_ids|vehicle_shortnames] [track-count] [max-score]')
    print("  list                        Show latest 10 teamevents (no vehicles)")
    print("  show all                   Show all teamevents (no vehicles)")
    print("  show <id>                  Show single teamevent with vehicles")
    print("  edit <id> [--name NAME] [--tracks NUM] [--vehicles 1,2,3] [--score SCORE]")
    print("  delete <id>")


def add_teamevent(args):
    if len(args) < 2:
        print('Usage: teamevent add "<name>" <Jahr>/<KW> [vehicle_ids] [track-count] [max-score]')
        return

    name = args[0]
    try:
        year_str, week_str = args[1].split("/")
        iso_year = int(year_str)
        iso_week = int(week_str)
    except Exception:
        print("❌ Ungültiges Format für Jahr/KW. Beispiel: 2025/30")
        return

    tracks = 4
    max_score = 15000
    vehicle_inputs = []

    tail = args[2:]

    if tail and tail[-1].isdigit():
        max_score = int(tail.pop())
    if tail and tail[-1].isdigit():
        tracks = int(tail.pop())
    if tail:
        vehicle_inputs = [v.strip() for v in tail[0].split(",") if v.strip()]

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        resolved_ids = []
        for val in vehicle_inputs:
            if val.isdigit():
                resolved_ids.append(int(val))
            else:
                cur.execute("SELECT id FROM vehicle WHERE shortname = ?", (val,))
                row = cur.fetchone()
                if row:
                    resolved_ids.append(row[0])
                else:
                    print(f"⚠️  Fahrzeug '{val}' nicht gefunden (weder ID noch shortname).")

        try:
            cur.execute(
                """
                INSERT INTO teamevent (name, iso_year, iso_week, tracks, max_score_per_track)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, iso_year, iso_week, tracks, max_score)
            )
            teamevent_id = cur.lastrowid

            for vid in resolved_ids:
                try:
                    cur.execute(
                        "INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (?, ?)",
                        (teamevent_id, vid)
                    )
                except sqlite3.IntegrityError:
                    print(f"⚠️  Vehicle ID {vid} does not exist or is already linked.")

            # Statt einfachem print → gleich Teamevent anzeigen
            conn.commit()
            show_teamevent([str(teamevent_id)])

        except sqlite3.IntegrityError:
            print(f"❌ Teamevent für KW {iso_week}/{iso_year} existiert bereits.")


def list_teamevents():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, iso_year, iso_week
            FROM teamevent ORDER BY iso_year DESC, iso_week DESC LIMIT 10
        """)
        events = cur.fetchall()

        print(f"{'ID.':>4} {'Jahr':<6} {'KW':<4}  {'Name'}")
        print("-" * 40)

        for eid, name, iso_year, iso_week in events:
            print(f"{eid:>3}. {iso_year:<6} {iso_week:<4}  {name}")

def show_teamevent(args):
    if not args:
        print("Usage: teamevent show all | <id>")
        return

    if args[0] == "all":
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, iso_year, iso_week, tracks, max_score_per_track
                FROM teamevent ORDER BY iso_year DESC, iso_week DESC
            """)
            events = cur.fetchall()

            print(f"{'ID.':>4} {'Jahr':<6} {'KW':<4}  {'Name':<25}  {'Tracks':<6}  {'Score/Track':<12}")
            print("-" * 70)

            for eid, name, year, week, tracks, score in events:
                print(f"{eid:>3}. {year:<6} {week:<4}  {name:<25}  {tracks:<6}  {score:<12}")
    else:
        try:
            eid = int(args[0])
        except ValueError:
            print("❌ Invalid ID")
            return

        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, iso_year, iso_week, tracks, max_score_per_track
                FROM teamevent WHERE id = ?
            """, (eid,))
            row = cur.fetchone()
            if not row:
                print(f"❌ Teamevent {eid} not found.")
                return

            te_id, name, year, week, tracks, score = row
            print(f"\nTeamevent {te_id}:")
            print(f"  Name         : {name}")
            print(f"  Jahr/KW      : {year}/KW{week}")
            print(f"  Tracks       : {tracks}")
            print(f"  Score/Track  : {score}")
            print(f"  Vehicles     :")

            cur.execute("""
                SELECT v.id, v.name
                FROM teamevent_vehicle tv
                JOIN vehicle v ON tv.vehicle_id = v.id
                WHERE tv.teamevent_id = ?
                ORDER BY v.id
            """, (te_id,))
            vehicles = cur.fetchall()
            if vehicles:
                for vid, vname in vehicles:
                    print(f"    - {vid}: {vname}")
            else:
                print("    (none)")

def edit_teamevent(args):
    if len(args) < 1:
        print("Usage: teamevent edit <id> [--name NAME] [--tracks NUM] [--vehicles 1,2,3] [--score SCORE]")
        return

    eid = int(args[0])
    name = None
    tracks = max_score = None
    vehicle_ids = None

    i = 1
    while i < len(args):
        if args[i] == "--name":
            i += 1
            name = args[i]
        elif args[i] == "--tracks":
            i += 1
            tracks = int(args[i])
        elif args[i] == "--score":
            i += 1
            max_score = int(args[i])
        elif args[i] == "--vehicles":
            i += 1
            vehicle_ids = [int(v.strip()) for v in args[i].split(",") if v.strip().isdigit()]
        i += 1

    fields = []
    values = []

    if name:
        fields.append("name = ?")
        values.append(name)
    if tracks is not None:
        fields.append("tracks = ?")
        values.append(tracks)
    if max_score is not None:
        fields.append("max_score_per_track = ?")
        values.append(max_score)

    with sqlite3.connect(DB_PATH) as conn:
        if fields:
            query = f"UPDATE teamevent SET {', '.join(fields)} WHERE id = ?"
            values.append(eid)
            conn.execute(query, values)
            print(f"✅ Teamevent {eid} updated.")

        if vehicle_ids is not None:
            conn.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (eid,))
            for vid in vehicle_ids:
                try:
                    conn.execute(
                        "INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (?, ?)",
                        (eid, vid)
                    )
                except sqlite3.IntegrityError:
                    print(f"⚠️  Vehicle ID {vid} does not exist or is already linked.")
            print(f"✅ Updated vehicles for Teamevent {eid}.")

def delete_teamevent(eid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (eid,))
        conn.execute("DELETE FROM teamevent WHERE id = ?", (eid,))
    print(f"🗑️  Teamevent {eid} deleted.")

