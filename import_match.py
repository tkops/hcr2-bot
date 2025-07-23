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
        print(f"❌ Kein Teamevent mit Namen '{name}' gefunden.")
        return None

    if len(matches) == 1:
        return matches[0][0]

    print(f"ℹ️  Mehrere Teamevents für '{name}' gefunden. Vergleiche mit Match-Datum {match_date.date()}:")
    best_id = None
    best_diff = None
    for te_id, year, week in matches:
        iso_start = datetime.fromisocalendar(year, week, 1)
        diff = abs((match_date - iso_start).days)
        print(f"  - ID {te_id}: {year}-KW{week}, Start {iso_start.date()}, Differenz {diff} Tage")
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_id = te_id

    print(f"✅ Beste Übereinstimmung: ID {best_id} mit {best_diff} Tagen Differenz")
    return best_id

def import_matches():
    with sqlite3.connect(DB_PATH) as conn:
        with open(TSV_FILE, newline='', encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            added = 0
            skipped = 0

            for row in reader:
                date_str = row["Datum"].strip()
                event = row["Event"].strip()
                opponent = row["Gegner"].strip()

                if not date_str or not event or not opponent:
                    skipped += 1
                    continue

                try:
                    match_date = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    skipped += 1
                    continue

                try:
                    score_ladys = int(row["score_ladys"].strip())
                except (KeyError, ValueError):
                    score_ladys = 0

                try:
                    score_opponent = int(row["score_opponent"].strip())
                except (KeyError, ValueError):
                    score_opponent = 0

                season_number = get_season_number(match_date)
                teamevent_id = get_teamevent_id(conn, event, match_date)

                if not teamevent_id:
                    print(f"⚠️  Kein passendes Teamevent gefunden für '{event}' am {date_str}")
                    skipped += 1
                    continue

                cur = conn.cursor()
                cur.execute("""
                    SELECT 1 FROM match
                    WHERE teamevent_id = ? AND season_number = ? AND start = ? AND opponent = ?
                """, (teamevent_id, season_number, date_str, opponent))
                if cur.fetchone():
                    skipped += 1
                    continue

                cur.execute("""
                    INSERT INTO match (teamevent_id, season_number, start, opponent, score_ladys, score_opponent)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (teamevent_id, season_number, date_str, opponent, score_ladys, score_opponent))
                added += 1

            conn.commit()
            print(f"✅ {added} Matches importiert, {skipped} übersprungen.")

if __name__ == "__main__":
    import_matches()

