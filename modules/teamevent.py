import sqlite3
from datetime import datetime

DB_PATH = "../hcr2-db/hcr2.db"

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
    print('  add "<name>" <year>/W<week> [vehicle_ids|vehicle_shortnames] [track-count] [max-score]')
    print("  list                        Show latest 10 teamevents (no vehicles)")
    print("  show all                   Show all teamevents (no vehicles)")
    print("  show <id>                  Show single teamevent with vehicles")
    print("  edit <id> [--name NAME] [--tracks NUM] [--vehicles 1,2,3] [--score SCORE]")
    print("  delete <id>")


def add_teamevent(args):
    if len(args) < 2:
        print('Usage:    .t add <name> <year>/W<week> [vehicle_ids] [track-count] [max-score-per-track]')
        print('Exmample: .t add The Best Teamevent ever 2025/30 be,ro,sm,sc,hc 5 15000')
        print('Exmample: .t add The Worst Teamevent ever 2025/31')
        return

    name = args[0]
    try:
        year_str, week_str = args[1].replace("W", "").split("/")
        iso_year = int(year_str)
        iso_week = int(week_str)
    except Exception:
        print("❌ Invalid year/week format. Example: 2025/30 or 2025/W30")
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
                    print(f"⚠️  Vehicle '{val}' not found (neither ID nor shortname).")

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

            conn.commit()
            print("✅ Teamevent added:")
            show_teamevent([str(teamevent_id)])

        except sqlite3.IntegrityError:
            print(f"❌ Teamevent for week {iso_week}/{iso_year} already exists.")


def list_teamevents():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, iso_year, iso_week
            FROM teamevent ORDER BY iso_year DESC, iso_week DESC LIMIT 10
        """)
        events = cur.fetchall()

        print(f"{'ID.':>4} {'Year':<6} {'Wk':<4}  {'Name'}")
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

            print(f"{'ID.':>4} {'Year':<6} {'Wk':<4}  {'Name':<25}  {'Tracks':<6}  {'Score/Track':<12}")
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
            print(f"  Year/Wk      : {year}/W{week}")
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
        print("Usage: teamevent edit <id> [--name NAME] [--tracks NUM] [--vehicles 1,2,3|codes] [--score SCORE]")
        return

    eid = int(args[0])
    name = None
    tracks = max_score = None
    vehicles_arg = None  # roher String nach --vehicles

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
            vehicles_arg = args[i].strip()
        i += 1

    fields = []
    values = []

    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if tracks is not None:
        fields.append("tracks = ?")
        values.append(tracks)
    if max_score is not None:
        fields.append("max_score_per_track = ?")
        values.append(max_score)

    import sqlite3
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        # Basis-Felder updaten
        if fields:
            values.append(eid)
            query = f"UPDATE teamevent SET {', '.join(fields)} WHERE id = ?"
            cur.execute(query, values)
            print(f"✅ Teamevent {eid} updated.")

        # Vehicles verarbeiten (optional)
        if vehicles_arg is not None:
            # Spezialfall: '-' bedeutet Liste leeren
            if vehicles_arg == "-":
                cur.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (eid,))
                print(f"✅ Cleared vehicles for Teamevent {eid}.")
            else:
                # Tokens splitten und normalisieren
                tokens = [t.strip() for t in vehicles_arg.split(",") if t.strip()]
                resolved_ids = []
                warnings = []

                def resolve_token(tok: str):
                    # 1) Direkte ID?
                    if tok.isdigit():
                        return int(tok)
                    # 2) Lookup per code/kurzname oder name (case-insensitive)
                    cur.execute("""
                        SELECT id
                        FROM vehicle
                        WHERE LOWER(shortname) = LOWER(?)
                           OR LOWER(name) = LOWER(?)
                        ORDER BY id
                        LIMIT 1
                    """, (tok, tok))
                    row = cur.fetchone()
                    return row[0] if row else None

                for tok in tokens:
                    vid = resolve_token(tok)
                    if vid is None:
                        warnings.append(tok)
                    else:
                        resolved_ids.append(vid)

                # Duplikate entfernen, Reihenfolge beibehalten
                seen = set()
                resolved_ids = [v for v in resolved_ids if not (v in seen or seen.add(v))]

                # Liste neu schreiben
                cur.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (eid,))
                for vid in resolved_ids:
                    try:
                        cur.execute(
                            "INSERT INTO teamevent_vehicle (teamevent_id, vehicle_id) VALUES (?, ?)",
                            (eid, vid)
                        )
                    except sqlite3.IntegrityError:
                        # Fremdschlüssel verletzt o.ä.
                        warnings.append(str(vid))

                if resolved_ids:
                    print(f"✅ Updated vehicles for Teamevent {eid}: {','.join(map(str, resolved_ids))}")
                else:
                    print(f"✅ Updated vehicles for Teamevent {eid}: (none)")

                if warnings:
                    print("⚠️  Unresolved/invalid vehicle tokens: " + ", ".join(warnings))




def delete_teamevent(eid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM teamevent_vehicle WHERE teamevent_id = ?", (eid,))
        conn.execute("DELETE FROM teamevent WHERE id = ?", (eid,))
    print(f"🗑️  Teamevent {eid} deleted.")

