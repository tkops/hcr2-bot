
import sqlite3

DB_PATH = "../hcr2-db/hcr2.db"

def print_help():
    print("Usage: python hcr2.py donations <command> [args]")
    print("\nCommands:")
    print("  add <player_id> <date> <total>    Add a donation snapshot")
    print("  delete <donation_id>              Delete a donation by ID")
    print("  show <player_id>                  Show last 10 donations and monthly average")

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
        if len(args) != 1:
            print("❌ Usage: donations show <player_id>")
            return
        show_donations(args[0])
    else:
        print(f"❌ Unknown command: {command}")
        print_help()

def add_donation(player_id, date, total):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO donation (player_id, date, total)
            VALUES (?, ?, ?)
            ON CONFLICT(player_id, date) DO UPDATE SET total = excluded.total
        """, (player_id, date, total))
        conn.commit()
        print(f"✅ Donation snapshot added for player {player_id} on {date} (total: {total})")
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
        print(f"✅ Donation {donation_id} deleted")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        conn.close()

def show_donations(player_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # Letzte 10 Snapshots (kumulierte Stände)
        cur.execute("""
            SELECT id, date, total
            FROM donation
            WHERE player_id = ?
            ORDER BY date DESC
            LIMIT 10
        """, (player_id,))
        rows = cur.fetchall()
        if not rows:
            print("ℹ️ No donations found for this player.")
            return

        print(f"Last 10 donation snapshots for player {player_id}:")
        for r in rows:
            print(f"  ID {r[0]} | Date: {r[1]} | Total (cumulative): {r[2]}")

        # Durchschnittliche monatliche Spendenhöhe:
        # 1) pro Monat den letzten Snapshot bestimmen
        # 2) Delta = total_monat - total_vormonat
        # 3) Durchschnitt über alle vorhandenen Monate (ohne den ersten, da kein Vormonat)
        cur.execute("""
            WITH per_month AS (
                SELECT
                    player_id,
                    strftime('%Y-%m', date) AS month,
                    MAX(date) AS last_date_in_month
                FROM donation
                WHERE player_id = ?
                GROUP BY player_id, month
            ),
            month_rows AS (
                SELECT d.player_id, d.date, d.total, strftime('%Y-%m', d.date) AS month
                FROM donation d
                JOIN per_month pm
                  ON d.player_id = pm.player_id
                 AND d.date = pm.last_date_in_month
                WHERE d.player_id = ?
            ),
            deltas AS (
                SELECT
                    month,
                    total,
                    LAG(total) OVER (ORDER BY date) AS prev_total
                FROM month_rows
                ORDER BY date
            )
            SELECT AVG(total - prev_total)
            FROM deltas
            WHERE prev_total IS NOT NULL;
        """, (player_id, player_id))
        avg = cur.fetchone()[0]

        if avg is None:
            print("\n📊 Not enough monthly data to compute an average (need at least 2 months).")
        else:
            print(f"\n📊 Average monthly donation increment: {avg:.2f}")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        conn.close()

