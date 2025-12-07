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
    print("  edit <donation_id> <total>        Edit total amount of a donation entry")
    print("  show [<player_id>]                Show last 10 entries + stats for one player")
    print("                                    Without player_id: show donation stats for all active players")
    print("  stats                             Show match count, donation total and index per active player")
    print("  under                             Show only players with donation index below 100 (for Discord bot)")
    print("  list [<date>]                     List donation dates or all entries for a specific date")


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

    elif command == "edit":
        if len(args) != 2:
            print("❌ Usage: donations edit <donation_id> <total>")
            return
        edit_donation(args[0], args[1])

    elif command == "show":
        if len(args) == 0:
            show_all_stats()
        elif len(args) == 1:
            show_player_donations(args[0])
        else:
            print("❌ Usage: donations show [<player_id>]")

    elif command == "stats":
        show_donation_index()

    elif command == "under":
        show_donation_index_under()

    elif command == "list":
        if len(args) == 0:
            list_donation_dates()
        elif len(args) == 1:
            list_donations_for_date(args[0])
        else:
            print("❌ Usage: donations list [<date>]")
    else:
        print(f"❌ Unknown command: {command}")
        print_help()


# ---------------- Core Functions ---------------- #


def add_donation(player_id, date, total):
    conn = None
    try:
        total_int = int(total)
        if total_int < 0:
            print("❌ total must be >= 0")
            return
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


def edit_donation(donation_id, new_total):
    """
    Edit only the 'total' field of a single donation entry.
    """
    conn = None
    try:
        total_int = int(new_total)
        if total_int < 0:
            print("❌ total must be >= 0")
            return

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # alten Eintrag holen
        cur.execute(
            """
            SELECT player_id, date, total
            FROM donation
            WHERE id = ?
            """,
            (donation_id,),
        )
        row = cur.fetchone()
        if not row:
            print(f"ℹ️ No donation with id {donation_id} found.")
            return

        player_id, date, old_total = row

        # updaten
        cur.execute(
            "UPDATE donation SET total = ? WHERE id = ?",
            (total_int, donation_id),
        )
        conn.commit()

        print(
            f"✅ Donation {donation_id} updated for player {player_id} on {date}: "
            f"{old_total} -> {total_int}"
        )

    except ValueError:
        print("❌ total must be an integer")
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


# -------- Shared calculation for donation index -------- #


def _compute_donation_index_results():
    """
    Returns (cutoff_date, results)

    results is a list of tuples:
      (player_id, name, matches, total, index)
    for all active PLTE players.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    try:
        # Stichtag: letzte notierte Spende
        cur.execute("SELECT MAX(date) FROM donation")
        row = cur.fetchone()
        if not row or row[0] is None:
            return None, []

        cutoff_date = row[0]

        # Aktive Spieler NUR Team PLTE
        cur.execute(
            "SELECT id, name FROM players "
            "WHERE active = 1 AND team = 'PLTE' "
            "ORDER BY id"
        )
        players = cur.fetchall()
        if not players:
            return cutoff_date, []

        results = []

        for pid, name in players:
            # Matches zählen
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

            # Aktueller Spendenstand
            cur.execute(
                """
                SELECT total FROM donation
                WHERE player_id = ?
                  AND date <= ?
                ORDER BY date DESC LIMIT 1
                """,
                (pid, cutoff_date),
            )
            drow = cur.fetchone()
            total = int(drow[0]) if drow and drow[0] is not None else 0

            expected = matches * 600
            index = (total / expected) * 100 if expected > 0 else 0.0

            results.append((pid, name, matches, total, index))

        return cutoff_date, results

    finally:
        conn.close()


# ---------------- New Stats / Index (all) ---------------- #


def show_donation_index():
    """
    List all active PLTE players with:
      - running number
      - ID
      - matches since STATS_START_DATE
      - donation total
      - index = (donation_total / (matches * 600)) * 100
    Sorted by index DESCENDING (lowest at bottom)
    """
    cutoff_date, results = _compute_donation_index_results()

    if cutoff_date is None:
        print("ℹ️ No donations found in database.")
        return

    if not results:
        print("ℹ️ No active players in team PLTE.")
        return

    # Sortierung: Index absteigend → niedrige Werte unten
    results.sort(key=lambda x: x[4], reverse=True)

    print(f"\n📊 Donation index from {STATS_START_DATE} to {cutoff_date}:")
    print(f"{'#':3} {'ID':4} {'Name':12} {'Mch':>4} {'Don':>8} {'Idx':>5}")
    print("-" * 50)

    for idx, (pid, name, matches, total, index) in enumerate(results, start=1):
        print(
            f"{idx:3d} {pid:4} {name[:12]:12} {matches:4d} "
            f"{format_k(total):>8} {index:5.1f}"
        )


# ---------------- New Stats / Index (under 100) ---------------- #


def show_donation_index_under():
    """
    Same as show_donation_index(), but only players with index < 100.
    Intended for Discord bot usage.
    """
    cutoff_date, results = _compute_donation_index_results()

    if cutoff_date is None:
        print("ℹ️ No donations found in database.")
        return

    # Filter: nur Index < 100
    results = [r for r in results if r[4] < 100.0]

    if not results:
        print("ℹ️ No players with donation index below 100 in team PLTE.")
        return

    # Sortierung: Index aufsteigend (schlechtester zuerst)
    results.sort(key=lambda x: x[4])

    print(f"\n📊 Donation index < 100 from {STATS_START_DATE} to {cutoff_date}:")
    print(f"{'#':3} {'ID':4} {'Name':12} {'Mch':>4} {'Don':>8} {'Idx':>5}")
    print("-" * 50)

    for idx, (pid, name, matches, total, index) in enumerate(results, start=1):
        print(
            f"{idx:3d} {pid:4} {name[:12]:12} {matches:4d} "
            f"{format_k(total):>8} {index:5.1f}"
        )


# ---------------- List dates / entries ---------------- #


def list_donation_dates():
    """
    Show unique donation dates with count of entries, like a sort -u on dates.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT date, COUNT(*) AS cnt
            FROM donation
            GROUP BY date
            ORDER BY date ASC
            """
        )
        rows = cur.fetchall()

        if not rows:
            print("ℹ️ No donations found.")
            return

        print("\n📅 Donation dates:")
        print(f"{'Date':12} {'Count':>5}")
        print("-" * 20)
        for ds, cnt in rows:
            print(f"{ds:12} {cnt:5d}")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if conn is not None:
            conn.close()


def list_donations_for_date(date_str: str):
    """
    Show all donation entries for a given date.
    """
    # Validierung des Datumsformats (aber Original-String für Query verwenden)
    try:
        _ = _parse_date(date_str)
    except Exception:
        print("❌ Invalid date format. Use YYYY-MM-DD or ISO 8601.")
        return

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.id, d.player_id, p.name, IFNULL(p.team, ''), d.total
            FROM donation d
            LEFT JOIN players p ON p.id = d.player_id
            WHERE d.date = ?
            ORDER BY p.team, p.name, d.player_id
            """,
            (date_str,),
        )
        rows = cur.fetchall()

        if not rows:
            print(f"ℹ️ No donations found for date {date_str}.")
            return

        print(f"\n📋 Donations for {date_str}:")
        print(f"{'ID':4} {'PID':4} {'Name':12} {'Team':4} {'Total':>8}")
        print("-" * 40)

        for did, pid, name, team, total in rows:
            short_name = (name or "")[:12]
            team_str = (team or "")[:4]
            print(
                f"{did:4d} {pid:4d} {short_name:12} {team_str:4} {format_k(total):>8}"
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
    avg_monthly = sum(month_deltas) / len(month_deltas) if month_deltas else 0.0

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

