#!/usr/bin/env python3
import csv
from datetime import datetime, timedelta
import subprocess
import os
import argparse
from typing import Optional, List, Dict, Tuple
from collections import defaultdict, Counter

# ----------------- CLI -----------------
parser = argparse.ArgumentParser()
parser.add_argument("--import", action="store_true", dest="do_import",
                    help="Führe Import aus (ohne Ausgabe pro Event, nur Summary).")
args = parser.parse_args()

TSV_PATH = "all.tsv"
if not os.path.exists(TSV_PATH):
    print("❌ Datei 'all.tsv' nicht gefunden.")
    raise SystemExit(1)

# ----------------- Helpers -----------------
def parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None

def kw_key_by_rule(d: datetime) -> Tuple[int, int]:
    """
    KW-Regel:
      - Sa/So -> aktuelle ISO-KW
      - Mo-Do -> ISO-KW der Vorwoche (d - 7 Tage)
      - Freitag -> NICHT hier behandeln (Sonderfall)
    """
    wd = d.weekday()  # Mo=0..So=6
    y, w, _ = d.isocalendar()
    if wd in (5, 6):  # Sa/So
        return y, w
    if wd in (0, 1, 2, 3):  # Mo-Do
        prev = d - timedelta(days=7)
        py, pw, _ = prev.isocalendar()
        return py, pw
    # Freitag -> Sonderfall, hier None signalisieren durch Exception
    raise ValueError("Friday must be handled separately")

def next_same_event_within(d: datetime, cluster_sorted: List[datetime],
                           max_delta_days: int = 15) -> Optional[datetime]:
    """Nächstes späteres Datum im selben 15-Tage-Cluster (gleicher Eventname)."""
    for nd in cluster_sorted:
        if nd <= d:
            continue
        if (nd - d).days <= max_delta_days:
            return nd
        break
    return None

# ----------------- Einlesen -----------------
# pro Eventname → sortierte, unique Datums-Liste
by_event_dates: Dict[str, List[datetime]] = defaultdict(list)
# pro Eventname → Tracks-Häufigkeiten (wir nehmen den häufigsten)
by_event_tracks: Dict[str, Counter] = defaultdict(Counter)

with open(TSV_PATH, newline='', encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        event = (row.get("Event") or "").strip()
        date_str = (row.get("Datum") or "").strip()
        tracks_str = (row.get("Rennen") or "").strip()
        if not event or not date_str or not tracks_str.isdigit():
            continue
        d = parse_date(date_str)
        if not d:
            continue
        by_event_dates[event].append(d)
        by_event_tracks[event][int(tracks_str)] += 1

# sort & unique
for ev in by_event_dates:
    by_event_dates[ev] = sorted(set(by_event_dates[ev]))

# ----------------- Clustering + Mapping auf (year, week) -----------------
# Ergebnis: key=(year, week, event) -> {event, tracks, year, week, anchor}
planned: Dict[Tuple[int, int, str], Dict[str, object]] = {}
ambiguous_fridays: List[Tuple[str, datetime]] = []

for ev, dates in by_event_dates.items():
    if not dates:
        continue

    # Tracks: häufigster Wert für dieses Event
    tracks = 0
    if by_event_tracks[ev]:
        tracks = by_event_tracks[ev].most_common(1)[0][0]

    # 15-Tage-Cluster bilden
    clusters: List[List[datetime]] = []
    current: List[datetime] = []
    prev = None
    for d in dates:
        if prev is None or (d - prev).days <= 15:
            current.append(d)
        else:
            clusters.append(current)
            current = [d]
        prev = d
    if current:
        clusters.append(current)

    # jeden Cluster auf genau eine (year, week) mappen
    for cluster in clusters:
        cluster = sorted(cluster)
        kw: Optional[Tuple[int, int]] = None
        anchor_date: Optional[datetime] = None

        for d in cluster:
            wd = d.weekday()
            if wd in (5, 6):  # Sa/So
                kw = kw_key_by_rule(d)
                anchor_date = d
                break
            elif wd in (0, 1, 2, 3):  # Mo-Do
                kw = kw_key_by_rule(d)
                anchor_date = d
                break
            else:  # Freitag -> Lookahead
                nxt = next_same_event_within(d, cluster, 15)
                if nxt is not None:
                    # falls der nächste auch Freitag ist, noch einen Schritt
                    target = nxt
                    if nxt.weekday() == 4:
                        nxt2 = next_same_event_within(nxt, cluster, 15)
                        if nxt2 is not None:
                            target = nxt2
                    # nur wenn target nicht Freitag ist, ist's eindeutig
                    if target.weekday() != 4:
                        try:
                            kw = kw_key_by_rule(target)
                            anchor_date = target
                            break
                        except ValueError:
                            pass
                else:
                    # Freitag ohne Folge im Cluster -> merken (ambig, wenn sonst nichts gefunden wird)
                    ambiguous_fridays.append((ev, d))

        if kw is None:
            # Nichts Eindeutiges gefunden:
            # bevorzugt Sa/So, dann Mo-Do; wenn nur Freitage -> ambig & skip
            choice = None
            for d in cluster:
                if d.weekday() in (5, 6):
                    choice = d
                    break
            if choice is None:
                for d in cluster:
                    if d.weekday() in (0, 1, 2, 3):
                        choice = d
                        break
            if choice is None:
                # nur Freitage in diesem Cluster -> zeigen als ambig, nicht anlegen
                for d in cluster:
                    ambiguous_fridays.append((ev, d))
                continue
            kw = kw_key_by_rule(choice)
            anchor_date = choice

        year, week = kw
        key = (year, week, ev)
        if key not in planned or (anchor_date is not None and anchor_date < planned[key]["anchor"]):
            planned[key] = {
                "event": ev,
                "tracks": tracks or 4,
                "year": year,
                "week": week,
                "anchor": anchor_date or cluster[0],
            }

# ----------------- Import / Ausgabe -----------------
events_sorted = sorted(planned.values(), key=lambda x: (x["year"], x["week"], x["event"]))

if args.do_import:
    added = already_exists = failed = 0
    failures: List[Tuple[Dict[str, object], str, str]] = []

    for e in events_sorted:
        cmd = [
            "python3", "hcr2.py", "teamevent", "add",
            e["event"],
            f"{e['year']}/{e['week']}",
            str(e["tracks"]),
            "15000",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
            low = out.lower()
            if proc.returncode != 0:
                failed += 1
                failures.append((e, f"rc={proc.returncode}", out.strip()))
            elif ("already exists" in low
                  or "existiert bereits" in low
                  or "schon vorhanden" in low
                  or "bereits vorhanden" in low):
                already_exists += 1
            else:
                added += 1
        except Exception as ex:
            failed += 1
            failures.append((e, f"exc={type(ex).__name__}", str(ex)))

    total = len(events_sorted)
    print(f"\n✅ Teamevent-Import abgeschlossen.")
    print(f"   Geplant: {total}")
    print(f"   Neu angelegt: {added}")
    print(f"   Bereits vorhanden: {already_exists}")
    print(f"   Fehlgeschlagen: {failed}")

    if ambiguous_fridays:
        print("\n❓ Ambige Freitage (nur Freitage im 15-Tage-Block, keine eindeutige Zuordnung):")
        shown = set()
        for ev, d in sorted(ambiguous_fridays, key=lambda x: (x[0], x[1])):
            key = (ev, d.date())
            if key in shown:
                continue
            shown.add(key)
            print(f"  {d.date()} | event='{ev}'")

    if failed:
        print("\n❌ Fehlgeschlagene Einträge (kompakt):")
        for e, why, _detail in failures:
            print(f"  {e['year']}/{e['week']} | '{e['event']}' | tracks={e['tracks']} | {why}")

else:
    print("\n📝 Dry-Run (kein Import ausgeführt)")
    print(f"   Gefundene Teamevents: {len(events_sorted)}\n")
    for e in events_sorted:
        print(f"  {e['year']}/{e['week']} | '{e['event']}' | tracks={e['tracks']} (anchor={e['anchor'].date()})")
    if ambiguous_fridays:
        print("\n❓ Ambige Freitage (nur Freitage im 15-Tage-Block, keine eindeutige Zuordnung):")
        shown = set()
        for ev, d in sorted(ambiguous_fridays, key=lambda x: (x[0], x[1])):
            key = (ev, d.date())
            if key in shown:
                continue
            shown.add(key)
            print(f"  {d.date()} | event='{ev}'")
    print("\n   (Führe mit --import aus, um sie anzulegen.)")

