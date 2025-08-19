#!/usr/bin/env python3
import csv
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import argparse

DB_PATH = "db/hcr2.db"
TSV_FILE = "all.tsv"
WINDOW_DAYS = 15  # ±7 Tage "grob passt"

parser = argparse.ArgumentParser()
parser.add_argument("--import", action="store_true", dest="do_import",
                    help="Führe Import in die DB aus (sonst nur Dry-Run + Summary).")
args = parser.parse_args()

# ---------- Helpers ----------

def parse_date(s):
    try:
        return datetime.strptime((s or "").strip(), "%Y-%m-%d")
    except Exception:
        return None

def get_season_number(date):
    base = datetime(2021, 5, 1)
    delta = (date.year - base.year) * 12 + (date.month - base.month)
    return delta + 1

def load_te_anchor_by_name(conn):
    """
    Lädt alle Teamevents: name -> Liste[(id, anchor_date)]
    anchor_date = Freitag (iso_monday + 4 Tage) der (iso_year, iso_week)
    """
    cur = conn.cursor()
    cur.execute("SELECT id, name, iso_year, iso_week FROM teamevent")
    by_name = defaultdict(list)
    for te_id, name, y, w in cur.fetchall():
        iso_monday = datetime.fromisocalendar(int(y), int(w), 1)
        anchor = iso_monday + timedelta(days=4)  # Freitag der KW
        by_name[name].append((te_id, anchor))
    # nach Datum sortieren für Reproduzierbarkeit
    for k in list(by_name.keys()):
        by_name[k].sort(key=lambda x: x[1])
    return by_name

def pick_te_for_match(name, match_dt, by_name):
    """
    Wähle das TE gleichen Namens mit kleinstem Tagesabstand zum Match-Datum.
    Nur akzeptieren, wenn |diff| <= WINDOW_DAYS. Sonst None.
    """
    cands = by_name.get(name)
    if not cands:
        return None
    best = None
    best_diff = None
    for te_id, anchor in cands:
        diff = abs((match_dt - anchor).days)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = te_id
    if best is not None and best_diff is not None and best_diff <= WINDOW_DAYS:
        return best
    return None

# ---------- Main ----------

def import_matches():
    # 1) TSV komplett lesen und Unique Matches bilden
    scores_total = 0
    malformed_scores = 0
    missing_fields_scores = 0

    # Unique Matches: key = (date_str, event, opponent)
    match_groups = {}  # key -> {"date": dt, "event": str, "opponent": str, "pl": int, "opp": int}

    with open(TSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            scores_total += 1
            event = (row.get("Event") or "").strip()
            date_str = (row.get("Datum") or "").strip()
            opponent = (row.get("Gegner") or "").strip()
            if not event or not date_str or not opponent:
                missing_fields_scores += 1
                continue
            d = parse_date(date_str)
            if not d:
                malformed_scores += 1
                continue

            # Scores aus der Zeile (leer -> 0)
            try:
                pl = int((row.get("Score PL") or "0").strip())
            except Exception:
                pl = 0
            try:
                opp = int((row.get("Score Gegner") or "0").strip())
            except Exception:
                opp = 0

            key = (date_str, event, opponent)
            if key not in match_groups:
                match_groups[key] = {"date": d, "event": event, "opponent": opponent, "pl": pl, "opp": opp}
            else:
                g = match_groups[key]
                if pl > g["pl"]:
                    g["pl"] = pl
                if opp > g["opp"]:
                    g["opp"] = opp

    unique_matches = list(match_groups.values())

    counts = {
        "unique_matches": len(unique_matches),
        "inserted": 0,
        "dup_in_db": 0,
        "missing_te": 0,
    }
    missing_te_list = []  # (date_str, event, opponent)

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        te_by_name = load_te_anchor_by_name(conn)

        for m in sorted(unique_matches, key=lambda x: (x["date"], x["event"], x["opponent"])):
            date_dt = m["date"]
            date_str = date_dt.strftime("%Y-%m-%d")
            event = m["event"]
            opponent = m["opponent"]
            pl = m["pl"]
            opp = m["opp"]

            season_number = get_season_number(date_dt)

            te_id = pick_te_for_match(event, date_dt, te_by_name)
            if te_id is None:
                counts["missing_te"] += 1
                missing_te_list.append((date_str, event, opponent))
                continue

            # Duplikate vermeiden
            cur.execute("""
                SELECT 1 FROM match
                WHERE teamevent_id = ? AND season_number = ? AND start = ? AND opponent = ?
            """, (te_id, season_number, date_str, opponent))
            if cur.fetchone():
                counts["dup_in_db"] += 1
                continue

            if args.do_import:
                cur.execute("""
                    INSERT INTO match (teamevent_id, season_number, start, opponent, score_ladys, score_opponent)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (te_id, season_number, date_str, opponent, pl, opp))
            counts["inserted"] += 1

        if args.do_import:
            conn.commit()

    # 3) Summary
    print(f"✅ Scores gelesen:        {scores_total}")
    print(f"   ↳ Unique Matches:      {counts['unique_matches']}")
    print(f"   ↳ Importiert:          {counts['inserted']}")
    print(f"   ↳ Bereits in DB:       {counts['dup_in_db']}")
    print(f"   ↳ Kein Teamevent:      {counts['missing_te']}")
    print(f"   ↳ Scores ohne Felder:  {missing_fields_scores}")
    print(f"   ↳ Scores malformed:    {malformed_scores}")

    if missing_te_list:
        print("\n❓ Kein passendes TE gefunden (pro Match):")
        shown = set()
        for date_str, ev, opp in sorted(missing_te_list, key=lambda x: (x[0], x[1], x[2])):
            key = (date_str, ev, opp)
            if key in shown:
                continue
            shown.add(key)
            print(f"  {date_str} | event='{ev}' | opponent='{opp}'")

if __name__ == "__main__":
    import_matches()

