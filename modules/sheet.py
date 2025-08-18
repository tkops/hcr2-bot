import sqlite3
from typing import Optional
import os
import re
from openpyxl import Workbook, load_workbook
from pathlib import Path
import sys
from secrets_config import NEXTCLOUD_AUTH
import subprocess
from datetime import datetime, date

DB_PATH = "db/hcr2.db"
NEXTCLOUD_BASE = Path("Power-Ladys/Scores")
NEXTCLOUD_URL = "http://192.168.178.101:8080/remote.php/dav/files/{user}/{path}"


def sanitize_filename(s):
    return re.sub(r'[^A-Za-z0-9_]', '', s.replace(' ', '_'))


def get_match_info(conn, match_id):
    c = conn.cursor()
    c.execute("""
        SELECT m.id, m.start, m.season_number, m.opponent, e.name
        FROM match m
        JOIN teamevent e ON m.teamevent_id = e.id
        WHERE m.id = ?
    """, (match_id,))
    return c.fetchone()


def get_active_players(conn):
    """
    Holt aktive PLTE-Spieler inkl. Abwesenheitsfenster.
    """
    c = conn.cursor()
    c.execute("""
        SELECT id, name, away_from, away_until
        FROM players
        WHERE active = 1 AND team = 'PLTE'
        ORDER BY name
    """)
    return c.fetchall()


def _parse_date_or_none(s: str):
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    # Versuche ISO first (YYYY-MM-DD)
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        pass
    # Fallback: DD.MM.YYYY
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except Exception:
        return None


def _is_absent_on(match_day: date, frm: Optional[str], until: Optional[str]) -> bool:
    """
    True, wenn match_day innerhalb [away_from, away_until] (inkl. Grenzen) liegt.
    Beide Felder sind TEXT / NULL. Teilintervalle werden sinnvoll interpretiert.
    """
    d_from = _parse_date_or_none(frm)
    d_until = _parse_date_or_none(until)

    if d_from and d_until:
        return d_from <= match_day <= d_until
    if d_from and not d_until:
        return d_from <= match_day
    if not d_from and d_until:
        return match_day <= d_until
    return False


def upload_to_nextcloud(local_path, remote_path):
    import requests
    user, password = NEXTCLOUD_AUTH
    remote_path = str(remote_path).lstrip("/")
    url = NEXTCLOUD_URL.format(user=user, path=remote_path)

    # existiert Datei schon?
    res = requests.head(url, auth=(user, password))
    if res.status_code == 200:
        return url, False

    # Ordnerkette anlegen (MKCOL)
    parts = remote_path.split("/")[:-1]
    current_path = ""
    for part in parts:
        current_path += f"/{part}"
        dir_url = NEXTCLOUD_URL.format(user=user, path=current_path.lstrip("/"))
        requests.request("MKCOL", dir_url, auth=(user, password))

    with open(local_path, "rb") as f:
        res = requests.put(url, auth=(user, password), data=f)
    if res.status_code in (200, 201, 204):
        return url, True
    return None, False


def download_from_nextcloud(season, filename, local_path):
    user, password = NEXTCLOUD_AUTH
    remote_path = f"Power-Ladys/Scores/S{season}/{filename}"
    url = NEXTCLOUD_URL.format(user=user, path=remote_path)

    curl_cmd = [
        "curl", "-s", "-u", f"{user}:{password}", "-H", "Cache-Control: no-cache", "-o", str(local_path), url
    ]
    subprocess.run(curl_cmd, capture_output=True)


def generate_excel(match, players, output_path):
    """
    players: Liste von Tupeln (id, name, away_from, away_until)
    Excel-Spalten:
      A: MatchID
      B: PlayerID
      C: Player
      D: Score
      E: Points
      F: Absent   <-- neu
    """
    match_id, match_date_str, season, opponent, event = match

    # Match-Datum bestimmen (für Abwesenheitsprüfung)
    md = _parse_date_or_none(match_date_str)
    # Fallback, falls None: setze auf ein Datum, das nie im Intervall liegt.
    if md is None:
        md = date(1970, 1, 1)

    safe_event = sanitize_filename(event)
    safe_opponent = sanitize_filename(opponent)
    filename = f"{match_id}_{safe_event}_{safe_opponent}.xlsx"
    folder = output_path / f"S{season}"
    filepath = folder / filename

    folder.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Match Info"

    ws.append([f"Match ID: {match_id}", f"Date: {match_date_str}", f"Season: {season}", f"Opponent: {opponent}", f"Event: {event}"])
    ws.append(["MatchID", "PlayerID", "Player", "Score", "Points", "Absent"])

    for pid, name, a_from, a_until in players:
        absent_flag = _is_absent_on(md, a_from, a_until)
        ws.append([match_id, pid, name, "", "", "true" if absent_flag else "false"])

    wb.save(filepath)

    remote_path = NEXTCLOUD_BASE / f"S{season}" / filename
    upload_to_nextcloud(filepath, remote_path)

    if filepath.exists():
        try:
            filepath.unlink()
        except Exception:
            pass

    web_url = f"http://cloud-pl.de?path=/Scores/S{season}"
    return f"[{filename}]({web_url})", True


def import_excel_to_matchscore(match_id):
    with sqlite3.connect(DB_PATH) as conn:
        match = get_match_info(conn, match_id)
        if not match:
            print("[ERROR] No match found")
            return

        match_id, _, season, opponent, event = match
        safe_event = sanitize_filename(event)
        safe_opponent = sanitize_filename(opponent)
        filename = f"{match_id}_{safe_event}_{safe_opponent}.xlsx"
        local_path = Path("tmp") / filename
        tsv_path = Path("tmp") / f"sheet_{match_id}.tsv"

        tsv_path.parent.mkdir(parents=True, exist_ok=True)
        download_from_nextcloud(season, filename, local_path)

        wb = load_workbook(filename=local_path, data_only=True)
        ws = wb.active

        with open(tsv_path, "w", encoding="utf-8") as f:
            for row in ws.iter_rows(min_row=3, values_only=True):
                # Row hat jetzt bis zu 6 Spalten: MatchID, PlayerID, Player, Score, Points, Absent
                # Wir ignorieren "Player" (Index 2) und lesen Absent (Index 5), falls vorhanden.
                if not row or len(row) < 5 or not row[1]:
                    continue
                mid = row[0]
                pid = row[1]
                score = row[3] if len(row) >= 4 else 0
                points = row[4] if len(row) >= 5 else 0
                absent_raw = row[5] if len(row) >= 6 else "false"

                # Robust in int (0/1) normalisieren:
                def _to_bool01(x):
                    if x is None:
                        return 0
                    s = str(x).strip().lower()
                    if s in ("1", "true", "yes", "y", "ja"):
                        return 1
                    if s in ("0", "false", "no", "n", "nein", ""):
                        return 0
                    # falls was Komisches steht: 0
                    return 0

                try:
                    score = int(score) if score not in (None, "") else 0
                except Exception:
                    score = 0
                try:
                    points = int(points) if points not in (None, "") else 0
                except Exception:
                    points = 0

                absent01 = _to_bool01(absent_raw)

                # TSV Zeile: mid  pid  score  points  absent01
                f.write(f"{mid}\t{pid}\t{score}\t{points}\t{absent01}\n")

        imported = 0
        changed = 0
        with open(tsv_path, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 5:
                    # Backward-compat, falls alte Dateien ohne absent auftauchen
                    parts = parts + ["0"]
                mid, player_id, score, points, absent01 = parts[:5]
                cmd = [
                    "python", "hcr2.py", "matchscore", "add",
                    mid, player_id, score, points, absent01
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    imported += 1
                    if "CHANGED" in result.stdout:
                        changed += 1

        for path in (local_path, tsv_path):
            if path.exists():
                try:
                    path.unlink()
                except Exception:
                    pass

        web_url = f"http://cloud-pl.de?path=/Scores/S{season}"
        status = "Changed" if changed > 0 else "Unchanged"
        print(f"[OK] [{filename}]({web_url}) ({status}, {imported} imported, {changed} changed)")


def print_help():
    print("Usage: python hcr2.py sheet <command> <match_id>")
    print("\nCommands:")
    print("  create <match_id>   Create Excel file and upload to Nextcloud")
    print("  import <match_id>   Import scores from Excel file on Nextcloud")


def handle_command(command, args):
    if command == "create":
        if len(args) != 1:
            print("Usage: python hcr2.py sheet create <match_id>")
            return
        try:
            match_id = int(args[0])
        except ValueError:
            print("[ERROR] Match ID must be an integer.")
            return

        with sqlite3.connect(DB_PATH) as conn:
            match = get_match_info(conn, match_id)
            if not match:
                print("[ERROR] No match found")
                return
            players = get_active_players(conn)
            url, uploaded = generate_excel(match, players, output_path=NEXTCLOUD_BASE)
            print(f"[OK] {url} ({'Created' if uploaded else 'Already existed'})")

    elif command == "import":
        if len(args) != 1:
            print("Usage: python hcr2.py sheet import <match_id>")
            return
        try:
            match_id = int(args[0])
        except ValueError:
            print("[ERROR] Match ID must be an integer.")
            return
        import_excel_to_matchscore(match_id)

    else:
        print("[ERROR] Unknown command:", command)
        print_help()

