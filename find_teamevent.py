import csv
import sqlite3
from datetime import datetime

DB_PATH = "db/hcr2.db"
TSV_FILE = "all.tsv"

def get_season_number(date: datetime) -> int:
    base = datetime(2021, 5, 1)
    delta = (date.year - base.year) * 12 + (date.month - base.month)
    return delta + 1

def get_teamevent_id(conn, name: str, match_date: datetime):
    cur = conn.cursor()
    cur.execute("SELECT id, iso_year, iso_week FROM teamevent WHERE name = ?", (name,))
    matches = cur.fetchall()

    if not matches:
        return None

    if len(matches) == 1:
        return matches[0][0]

    # Mehrere Matches → bestes Datum wählen
    best_id = None
    best_diff = None

    for te_id, year, week in matches:
        # ISO-Wochenstart = Montag
        iso_start = datetime.fromisocalendar(year, week, 1)
        diff = abs((match_date - iso_start).days)

        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_id = te_id

    return best_id

def process_first_valid_row():
    with sqlite3.connect(DB_PATH) as conn:
        with open(TSV_FILE, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                date_str = row["Datum"].strip()
                event = row["Event"].strip()
                opponent = row["Gegner"].strip()

                if not date_str or not event or not opponent:
                    continue

                try:
                    match_date = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    continue

                season_number = get_season_number(match_date)
                teamevent_id = get_teamevent_id(conn, event, match_date)

                print("📅 Match:")
                print(f"  ➤ Datum:       {match_date.date()}")
                print(f"  ➤ Season:      {season_number}")
                print(f"  ➤ Event:       {event}")
                print(f"  ➤ Gegner:      {opponent}")
                print(f"  ➤ Teamevent-ID:{teamevent_id or '❌ nicht gefunden'}")
                break

if __name__ == "__main__":
    process_first_valid_row()

