import csv
from datetime import datetime, timedelta
import subprocess
import os
import argparse
import calendar

parser = argparse.ArgumentParser()
parser.add_argument("--import", action="store_true", dest="do_import", help="Führe Import aus")
args = parser.parse_args()

tsv_path = "all.tsv"
if not os.path.exists(tsv_path):
    print("❌ Datei 'all.tsv' nicht gefunden.")
    exit(1)

# (iso_year, iso_week) => {event, tracks, start_date}
events = {}

with open(tsv_path, newline='', encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        event = row["Event"].strip()
        date_str = row["Datum"].strip()
        tracks_str = row["Rennen"].strip()

        if not event or not date_str or not tracks_str.isdigit():
            continue

        try:
            match_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        # Rücksprung um eine Woche (ISO-Woche -1)
        ref_date = match_date - timedelta(days=7)
        iso_year, iso_week, _ = ref_date.isocalendar()

        # Teamevent-Start = Freitag der Ziel-KW
        monday = datetime.fromisocalendar(iso_year, iso_week, 1)
        friday = monday + timedelta(days=4)

        key = (iso_year, iso_week)
        if key not in events or match_date < events[key]["date"]:
            events[key] = {
                "event": event,
                "date": match_date,
                "start": friday,
                "tracks": int(tracks_str)
            }

# Ausgabe
for (year, week), data in sorted(events.items(), key=lambda x: x[1]["date"]):
    cmd = [
        "python", "hcr2.py", "teamevent", "add",
        f'"{data["event"]}"',
        data["start"].strftime("%Y-%m-%d"),
        str(data["tracks"]),
        '""',
        "15000"
    ]

    if args.do_import:
        subprocess.run(" ".join(cmd), shell=True)
    else:
        print(" ".join(cmd))

