import sqlite3
from datetime import datetime
from dateutil.relativedelta import relativedelta

DB_PATH = "db/hcr2.db"
VALID_DIVISIONS = {"DIV1", "DIV2", "DIV3", "DIV4", "DIV5", "DIV6", "DIV7", "CC"}


def handle_command(cmd, args):
    if cmd == "add":
        add_or_update_season(args)
    elif cmd == "list":
        list_seasons(args)
    elif cmd == "delete":
        delete_season(args)
    else:
        print(f"❌ Unknown season command: {cmd}")
        print_help()


def print_help():
    print("Usage: python hcr2.py season <command> [args]")
    print("\nAvailable commands:")
    print("  list                  → show last 10 seasons")
    print("  list all              → show all seasons")
    print("  list <number>         → show season by number")
    print("  list <division>       → show seasons in division (CC, DIV1–DIV7)")
    print("  add <number> [div]    → add/update season")
    print("  delete <number>       → delete season")


def add_or_update_season(args):
    if not args or not args[0].isdigit():
        print("Usage: season add <number> [division]")
        return

    number = int(args[0])
    division = args[1].upper() if len(args) > 1 else None

    if division and division not in VALID_DIVISIONS:
        print("❌ Invalid division. Use CC or DIV1 to DIV7.")
        return

    start = get_start_date(number)
    name = get_month_year_name(start)

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM season WHERE number = ?", (number,))
        exists = cur.fetchone()

        if exists:
            if division:
                conn.execute("UPDATE season SET division = ? WHERE number = ?", (division, number))
                print(f"🔁 Season {number} updated to division {division}")
            else:
                print(f"ℹ️ Season {number} already exists (no division update)")
        else:
            conn.execute(
                "INSERT INTO season (number, name, start, division) VALUES (?, ?, ?, ?)",
                (number, name, start, division or "")
            )
            print(f"✅ Season {number} ('{name}') added with start {start}")


def delete_season(args):
    if not args or not args[0].isdigit():
        print("Usage: season delete <number>")
        return

    number = int(args[0])
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM season WHERE number = ?", (number,))
        if not cur.fetchone():
            print(f"⚠️ Season {number} does not exist.")
            return

        conn.execute("DELETE FROM season WHERE number = ?", (number,))
        print(f"🗑️ Season {number} deleted.")


def get_start_date(number):
    base = datetime(2021, 5, 1)
    start = base + relativedelta(months=number - 1)
    return start.strftime("%Y-%m-%d")


def get_month_year_name(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%b %y")


def list_seasons(args):
    query = "SELECT number, name, start, division FROM season"
    params = []
    desc = "ORDER BY number DESC LIMIT 10"

    if not args:
        pass
    elif args[0].lower() == "all":
        desc = "ORDER BY number"
    elif args[0].isdigit():
        query += " WHERE number = ?"
        params = [int(args[0])]
        desc = ""
    else:
        div = args[0].upper()
        if div not in VALID_DIVISIONS:
            print("❌ Invalid division. Use CC or DIV1 to DIV7.")
            return
        query += " WHERE division = ?"
        params = [div]
        desc = "ORDER BY number"

    query = f"{query} {desc}"

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()

    print(f"{'No.':3}   {'Name':<8} {'Div':<6}")
    print("-" * 25)
    for number, name, _, division in rows:
        print(f"{number:>3}.  {name:<8} {division:<6}")

