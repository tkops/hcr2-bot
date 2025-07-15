import sqlite3, sys

DB_PATH = "db/hcr2.db"

def soft_delete(pid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE players SET active = 0 WHERE id = ?", (pid,))
    print(f"✅ Player {pid} deactivated.")

def hard_delete(pid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM players WHERE id = ?", (pid,))
    print(f"🗑️  Player {pid} permanently removed.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python delete_player.py <id> [--hard]")
        sys.exit(1)

    player_id = int(sys.argv[1])
    hard = len(sys.argv) > 2 and sys.argv[2] == "--hard"

    if hard:
        hard_delete(player_id)
    else:
        soft_delete(player_id)

