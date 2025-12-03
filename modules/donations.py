
import sqlite3
import os
from datetime import datetime

DB_PATH = "../hcr2-db/hcr2.db"

def print_help():
    print("Usage: python hcr2.py donations <command> [args]")
    print("\nCommands:")
    print("  add <player_id> <date> <total>    Add a donation snapshot (cumulative total)")
    print("  delete <donation_id>              Delete a donation by ID")
    print("  show [<player_id>]                Show last 10 entries + stats for one player")
    print("                                    Without player_id: show stats for all active players")
    print("  stats                             Alias: show stats for all active players")

def handle_command(command, args):
    if command == "add":
        if len(args) != 3:
            print("❌ Usage: donations add <player_id> <date> <total>")
            return
        add_donation(args[0], args[1], args[2])

    elif command == "delete":
        if len(args) != 1:
            print("❌ Usage: donations delete <donation_id>")
            return
        delete_donation(args[0])

    elif command == "show":
        if len(args) == 0:
            show_all_stats()
        elif len(args) == 1:
            show_player_donations(args[0])
        else:
            print("❌ Usage: donations show [<player_id>]")

    elif command == "stats":
        show_all_stats()

    else:
        print(f"❌ Unknown command: {command}")
        print_help()

# ---------------- Core Functions ---------------- #

def add_donation(player_id, date, total):
    try:
        total_int = int(total)
        _ = _parse_date(date)
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO donation (player_id, date, total)
            VALUES (?, ?, ?)
            ON CONFLICT(player_id, date) DO UPDATE SET total = excluded.total
        """, (player_id, date, total_int))
        conn.commit()
        print(f"✅ Donation snapshot added for player {player_id} on {date} (total: {total_int})")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        conn.close()

def delete_donation(donation_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM donation WHERE id = ?", (donation_id,))
        conn.commit()
        if cur.rowcount == 0:
            print(f"ℹ️ No donation with id {donation_id} found.")
        else:
            print(f"✅ Donation {donation_id} deleted")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        conn.close()

# ---------------- Show for One Player ---------------- #

def show_player_donations(player_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT name FROM players WHERE id = ?", (player_id,))
        row = cur.fetchone()
        if not row:
            print("❌ Player not found.")
            return
        player_name = row[0]

        cur.execute("""
            SELECT date, total FROM donation
            WHERE player_id = ?
            ORDER BY date ASC
        """, (player_id,))
        all_snapshots = cur.fetchall()
        if not all_snapshots:
            print(f"ℹ️ No donations found for {player_name}.")
            return

        stats = calculate_stats(all_snapshots)

        print(f"\n📌 Donations for {player_name} (ID {player_id}):")
        print(f"{'Date':12} {'Total':>8} {'Delta':>8}")
        print("-" * 28)

        last_ten = stats["entries"][-10:]
        for ds, tot, delta in reversed(last_ten):
            print(f"{ds:12} {format_k(tot):>8} {format_k(delta):>8}")

        print("\n📊 Stats:")
        print(f"  Average monthly increment: {format_k(stats['avg_monthly_increment'])}")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        conn.close()

# ---------------- Show All Players ---------------- #

def show_all_stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM players WHERE active = 1")
        players = cur.fetchall()

        if not players:
            print("ℹ️ No active players.")
            return

        print("\n📊 Donations (K):")
        print(f"{'Name':12} {'Tot':>6} {'Inc':>6} {'Avg':>6}")
        print("-" * 32)

        for pid, name in players:
            cur.execute("""
                SELECT date, total FROM donation
                WHERE player_id = ?
                ORDER BY date ASC
            """, (pid,))
            snapshots = cur.fetchall()
            stats = calculate_stats(snapshots)
            last_inc = stats["entries"][-1][2] if stats["entries"] else 0
            short_name = name[:12]
            print(f"{short_name:12} {format_k(stats['last_total']):>6} {format_k(last_inc):>6} {format_k(stats['avg_monthly_increment']):>6}")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        conn.close()

# ---------------- Helper ---------------- #

def calculate_stats(snapshots):
    if not snapshots:
        return {"entries": [], "last_total": 0, "total_donated": 0, "avg_monthly_increment": 0.0}

    parsed = []
    for ds, total in snapshots:
        dt = _parse_date(ds)
        parsed.append((dt, ds, int(total)))
    parsed.sort(key=lambda x: x[0])

    entries = []
    total_donated = 0
    prev_total = None
    for dt, ds, tot in parsed:
        delta = 0 if prev_total is None else (tot - prev_total)
        entries.append((ds, tot, delta))
        if prev_total is not None:
            total_donated += delta
        prev_total = tot

    last_total = parsed[-1][2]

    month_last = {}
    for dt, ds, tot in parsed:
        key = f"{dt.year:04d}-{dt.month:02d}"
        if key not in month_last or dt > month_last[key][0]:
            month_last[key] = (dt, tot)

    month_points = sorted(month_last.items(), key=lambda kv: kv[1][0])
    month_deltas = []
    for i in range(1, len(month_points)):
        month_deltas.append(month_points[i][1][1] - month_points[i-1][1][1])
    avg_monthly = sum(month_deltas) / len(month_deltas) if month_deltas else 0.0

    return {"entries": entries, "last_total": last_total, "total_donated": total_donated, "avg_monthly_increment": avg_monthly}

def _parse_date(ds: str) -> datetime:
    try:
        return datetime.fromisoformat(ds)
    except ValueError:
        return datetime.strptime(ds, "%Y-%m-%d")

def format_k(value):
    try:
        val = float(value)
        return f"{val/1000:.1f}K"
    except:
        return str(value)

