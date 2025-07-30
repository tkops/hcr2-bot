import sqlite3
import os
from openpyxl import Workbook, load_workbook
from pathlib import Path
import sys
from secrets_config import NEXTCLOUD_AUTH
import subprocess

DB_PATH = "db/hcr2.db"
NEXTCLOUD_BASE = Path("Power-Ladys/Scores")
NEXTCLOUD_URL = "http://192.168.178.101:8080/remote.php/dav/files/{user}/{path}"

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
    c = conn.cursor()
    c.execute("""
        SELECT id, name FROM players
        WHERE active = 1 AND team = 'PLTE'
        ORDER BY name
    """)
    return c.fetchall()

def upload_to_nextcloud(local_path, remote_path):
    import requests
    user, password = NEXTCLOUD_AUTH
    remote_path = str(remote_path).lstrip("/")
    url = NEXTCLOUD_URL.format(user=user, path=remote_path)

    res = requests.head(url, auth=(user, password))
    if res.status_code == 200:
        return url, False

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
    match_id, match_date, season, opponent, event = match
    filename = f"{match_id}_{event.replace(' ', '_')}_{opponent.replace(' ', '_')}.xlsx"
    folder = output_path / f"S{season}"
    filepath = folder / filename

    folder.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Match Info"

    ws.append([f"Match ID: {match_id}", f"Date: {match_date}", f"Season: {season}", f"Opponent: {opponent}", f"Event: {event}"])
    ws.append(["MatchID", "PlayerID", "Player", "Score", "Points"])

    for pid, name in players:
        ws.append([match_id, pid, name, "", ""])

    wb.save(filepath)

    remote_path = NEXTCLOUD_BASE / f"S{season}" / filename
    url, uploaded = upload_to_nextcloud(filepath, remote_path)

    if filepath.exists():
        try:
            filepath.unlink()
        except:
            pass

    web_url = f"http://cloud-pl.de?path=/Scores/S{season}/{filename}"
    return web_url, uploaded
def import_excel_to_matchscore(match_id):
    with sqlite3.connect(DB_PATH) as conn:
        match = get_match_info(conn, match_id)
        if not match:
            print("[ERROR] No match found")
            return

        match_id, _, season, opponent, event = match
        filename = f"{match_id}_{event.replace(' ', '_')}_{opponent.replace(' ', '_')}.xlsx"
        local_path = Path("tmp") / filename
        tsv_path = Path("tmp") / f"sheet_{match_id}.tsv"

        tsv_path.parent.mkdir(parents=True, exist_ok=True)
        download_from_nextcloud(season, filename, local_path)

        wb = load_workbook(filename=local_path, data_only=True)
        ws = wb.active

        with open(tsv_path, "w", encoding="utf-8") as f:
            for row in ws.iter_rows(min_row=3, values_only=True):
                if not row or len(row) < 5 or not row[1]:
                    continue
                mid, pid, _, score, points = row
                try:
                    score = int(score) if score not in (None, "") else 0
                except:
                    score = 0
                try:
                    points = int(points) if points not in (None, "") else 0
                except:
                    points = 0
                f.write(f"{mid}\t{pid}\t{score}\t{points}\n")

        imported = 0
        changed = 0
        with open(tsv_path, encoding="utf-8") as f:
            for line in f:
                mid, player_id, score, points = line.strip().split("\t")
                cmd = ["python", "hcr2.py", "matchscore", "add", mid, player_id, score, points]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    imported += 1
                    if "CHANGED" in result.stdout:
                        changed += 1

        for path in (local_path, tsv_path):
            if path.exists():
                try:
                    path.unlink()
                except:
                    pass

        web_url = f"http://cloud-pl.de?path=/Scores/S{season}/{filename}"
        status = "Changed" if changed > 0 else "Unchanged"
        print(f"[OK] {web_url} ({status}, {imported} imported, {changed} changed)")

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

