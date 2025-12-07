import sqlite3
from datetime import datetime

DB_PATH = "../hcr2-db/hcr2.db"

# Fester Startzeitpunkt für die Match-Zählung
STATS_START_DATE = "2025-11-01"


def print_help():
    print("Usage: python hcr2.py donations <command> [args]")
    print("\nCommands:")
    print("  add <player_id> <date> <total>    Add a donation snapshot (cumulative total)")
    print("  delete <donation_id>              Delete a donation by ID")
    print("  show [<player_id>]                Show last 10 entries + stats for one player")
    print("                                    Without player_id: show donation stats for all active players")
    print("  stats                             Show match count, donation total and index per active player")


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
        show_donation_index()

    else:
        print(f"❌ Unknown command: {command}")
        print_help()


# ---------------- Core Functions ---------------- #


def add_donation(player_id, date, total):
    conn = None
    try:
        total_int = int(total)
        _ = _parse_date(date)
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO donation (player_id, date, total)
            VALUES (?, ?, ?)
            ON CONFLICT(player_id, date) DO UPDATE SET total = excluded.total
            """,
            (player_id, date, total_int),
        )
        conn.commit()
        print(
            f"✅ Donation snapshot added for player {player_id} on {date} (total: {total_int})"
        )
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if conn is not None:
            conn.close()


def delete_donation(donation_id):
    conn = None
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
        if conn is not None:
            conn.close()


# ---------------- Show for One Player ---------------- #


def show_player_donations(player_id):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # Resolve player name
        cur.execute("SELECT name FROM players WHERE id = ?", (player_id,))
        row = cur.fetchone()
        if not row:
            print("❌ Player not found.")
            return
        player_name = row[0]

        # Load all snapshots including ID
        cur.execute(
            """
            SELECT id, date, total FROM donation
            WHERE player_id = ?
            ORDER BY date ASC
            """,
            (player_id,),
        )
        all_snapshots = cur.fetchall()
        if not all_snapshots:
            print(f"ℹ️ No donations found for {player_name}.")
            return

        stats = calculate_stats(all_snapshots)

        print(f"\n📌 Donations for {player_name} (ID {player_id}):")
        print(f"{'ID':4} {'Date':12} {'Total':>8} {'Delta':>8}")
        print("-" * 36)

        last_ten = stats["entries"][-10:]
        for donation_id, ds, tot, delta in reversed(last_ten):
            id_str = str(donation_id) if donation_id is not None else "-"
            print(f"{id_str:4} {ds:12} {format_k(tot):>8} {format_k(delta):>8}")

        print("\n📊 Stats:")
        print(
            f"  Average monthly increment: {format_k(stats['avg_monthly_increment'])}"
        )

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if conn is not None:
            conn.close()


# ---------------- Show All Players (Donation-Only-Stats) ---------------- #


def show_all_stats():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM players WHERE active = 1")
        players = cur.fetchall()

        if not players:
            print("ℹ️ No active players.")
            return

        print("\n📊 Donations (K):")
        # Player-ID in der ersten Spalte
        print(f"{'ID':4} {'Name':12} {'Tot':>6} {'Inc':>6} {'Avg':>6}")
        print("-" * 40)

        for pid, name in players:
            cur.execute(
                """
                SELECT date, total FROM donation
                WHERE player_id = ?
                ORDER BY date ASC
                """,
                (pid,),
            )
            snapshots = cur.fetchall()
            stats = calculate_stats(snapshots)
            # entries: (donation_id, ds, tot, delta)
            last_inc = stats["entries"][-1][3] if stats["entries"] else 0
            short_name = name[:12]
            print(
                f"{pid:4} {short_name:12} {format_k(stats['last_total']):>6} "
                f"{format_k(last_inc):>6} {format_k(stats['avg_monthly_increment']):>6}"
            )

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if conn is not None:
            conn.close()


# ---------------- New Stats / Index ---------------- #


def show_donation_index():
    """
    List all active players with:
      - ID
      - number of matches since STATS_START_DATE up to cutoff_date
      - current donation total (latest snapshot up to cutoff_date)
      - index = (donation_total / (matches * 600)) * 100
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # Stichtag: letzte notierte Spende
        cur.execute("SELECT MAX(date) FROM donation")
        row = cur.fetchone()
        if not row or row[0] is None:
            print("ℹ️ No donations found in database.")
            return
        cutoff_date = row[0]

        # Aktive Spieler
        cur.execute("SELECT id, name FROM players WHERE active = 1 ORDER BY id")
        players = cur.fetchall()
        if not players:
            print("ℹ️ No active players.")
            return

        print(f"\n📊 Donation index from {STATS_START_DATE} to {cutoff_date}:")
        print(f"{'ID':4} {'Name':12} {'Mch':>4} {'Don':>8} {'Idx':>5}")
        print("-" * 44)

        for pid, name in players:
            # Matches zählen (match.start laut Schema)
            cur.execute(
                """
                SELECT COUNT(DISTINCT m.id)
                FROM match m
                JOIN matchscore ms ON ms.match_id = m.id
                WHERE ms.player_id = ?
                  AND DATE(m.start) >= DATE(?)
                  AND DATE(m.start) <= DATE(?)
                """,
                (pid, STATS_START_DATE, cutoff_date),
            )
            mrow = cur.fetchone()
            matches = mrow[0] if mrow and mrow[0] is not None else 0

            # Aktueller Spendenstand (letzter Snapshot bis Stichtag)
            cur.execute(
                """
                SELECT total FROM donation
                WHERE player_id = ?
                  AND date <= ?
                ORDER BY date DESC
                LIMIT 1
                """,
                (pid, cutoff_date),
            )
            drow = cur.fetchone()
            total = int(drow[0]) if drow and drow[0] is not None else 0

            expected = matches * 600
            if expected > 0:
                index = (total / expected) * 100
            else:
                index = 0.0

            short_name = name[:12]
            print(
                f"{pid:4} {short_name:12} {matches:4d} {format_k(total):>8} {index:5.1f}"
            )

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if conn is not None:
            conn.close()


# ---------------- Helper ---------------- #


def calculate_stats(snapshots):
    """
    snapshots can be:
      - [(date, total), ...]
      - [(id, date, total), ...]
    Returns:
      {
        "entries": [(donation_id, ds, tot, delta), ...],
        "last_total": int,
        "total_donated": int,
        "avg_monthly_increment": float,
      }
    """
    if not snapshots:
        return {
            "entries": [],
            "last_total": 0,
            "total_donated": 0,
            "avg_monthly_increment": 0.0,
        }

    parsed = []
    for row in snapshots:
        if len(row) == 3:
            donation_id, ds, total = row
        elif len(row) == 2:
            donation_id = None
            ds, total = row
        else:
            # Unexpected shape, skip
            continue

        dt = _parse_date(ds)
        parsed.append((dt, donation_id, ds, int(total)))

    if not parsed:
        return {
            "entries": [],
            "last_total": 0,
            "total_donated": 0,
            "avg_monthly_increment": 0.0,
        }

    parsed.sort(key=lambda x: x[0])

    entries = []
    total_donated = 0
    prev_total = None

    for dt, donation_id, ds, tot in parsed:
        delta = 0 if prev_total is None else (tot - prev_total)
        entries.append((donation_id, ds, tot, delta))
        if prev_total is not None:
            total_donated += delta
        prev_total = tot

    last_total = parsed[-1][3]

    # Monthly aggregation (based on last snapshot per month)
    month_last = {}
    for dt, donation_id, ds, tot in parsed:
        key = f"{dt.year:04d}-{dt.month:02d}"
        if key not in month_last or dt > month_last[key][0]:
            month_last[key] = (dt, tot)

    month_points = sorted(month_last.items(), key=lambda kv: kv[1][0])
    month_deltas = []
    for i in range(1, len(month_points)):
        month_deltas.append(month_points[i][1][1] - month_points[i - 1][1][1])
    avg_monthly = sum(month_deltas) / len(month_points) if month_deltas else 0.0

    return {
        "entries": entries,
            "last_total": last_total,
            "total_donated": total_donated,
            "avg_monthly_increment": avg_monthly,
        }


def _parse_date(ds: str) -> datetime:
    try:
        return datetime.fromisoformat(ds)
    except ValueError:
        return datetime.strptime(ds, "%Y-%m-%d")


def format_k(value):
    try:
        val = float(value)
        return f"{val/1000:.1f}K"
    except Exception:
        return str(value)

