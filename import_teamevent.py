import csv
from datetime import datetime, timedelta
import subprocess
import os
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--import", action="store_true", dest="do_import", help="Führe Import aus")
args = parser.parse_args()

tsv_path = "all.tsv"
if not os.path.exists(tsv_path):
    print("❌ Datei 'all.tsv' nicht gefunden.")
    exit(1)

# (iso_year, iso_week) => {event, tracks, date}
events = {}

with open(tsv_path, newline='', encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        event = (row.get("Event") or "").strip()
        date_str = (row.get("Datum") or "").strip()
        tracks_str = (row.get("Rennen") or "").strip()

        if not event or not date_str or not tracks_str.isdigit():
            continue

        try:
            match_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        # Referenz: eine Woche vorher (ISO-KW)
        ref_date = match_date - timedelta(days=7)
        iso_year, iso_week, _ = ref_date.isocalendar()

        key = (iso_year, iso_week)
        # pro (Jahr, KW) den frühesten Matchtag nehmen (stabil)
        if key not in events or match_date < events[key]["date"]:
            events[key] = {
                "event": event,
                "date": match_date,
                "tracks": int(tracks_str),
                "year": iso_year,
                "week": iso_week,
            }

# Sortierte Liste der geplanten Events
planned = sorted(events.values(), key=lambda x: x["date"])

if args.do_import:
    added = 0
    already_exists = 0
    failed = 0
    failures = []

    for e in planned:
        cmd = [
            "python3", "hcr2.py", "teamevent", "add",
            e["event"],
            f"{e['year']}/{e['week']}",
            str(e["tracks"]),
            "15000",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,  # wir werten selbst aus
            )
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
            low = out.lower()

            if proc.returncode != 0:
                failed += 1
                failures.append((e, f"rc={proc.returncode}", out.strip()))
            elif ("already exists" in low or "existiert bereits" in low or "schon vorhanden" in low or "bereits vorhanden" in low):
                already_exists += 1
            else:
                added += 1
        except Exception as ex:
            failed += 1
            failures.append((e, f"exc={type(ex).__name__}", str(ex)))

    total = len(planned)
    print(f"\n✅ Teamevent-Import abgeschlossen.")
    print(f"   Geplant: {total}")
    print(f"   Neu angelegt: {added}")
    print(f"   Bereits vorhanden: {already_exists}")
    print(f"   Fehlgeschlagen: {failed}")

    if failed:
        print("\n❌ Fehlgeschlagene Einträge (kompakt):")
        for e, why, detail in failures:
            print(f"  {e['year']}/{e['week']} | {e['date'].date()} | '{e['event']}' | tracks={e['tracks']} | {why}")

else:
    # Dry-Run Summary
    print("\n📝 Dry-Run (kein Import ausgeführt)")
    print(f"   Gefundene (Jahr/KW)-Events: {len(planned)}\n")
    print("   Geplante Teamevents:")
    for e in planned:
        print(f"  {e['year']}/{e['week']} | {e['date'].date()} | '{e['event']}' | tracks={e['tracks']}")
    print("\n   (Führe mit --import aus, um sie anzulegen.)")

