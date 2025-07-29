import sqlite3
import os
from openpyxl import Workbook, load_workbook
from pathlib import Path
import sys
from secrets_config import NEXTCLOUD_AUTH
import subprocess
import tempfile

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

    # Prüfe, ob Datei schon existiert
    res = requests.head(url, auth=(user, password))
    if res.status_code == 200:
        print("[INFO] File already exists in Nextcloud:", remote_path)
        return url

    # Verzeichnisstruktur erstellen
    parts = remote_path.split("/")[:-1]  # ohne Dateiname
    current_path = ""
    for part in parts:
        current_path += f"/{part}"
        dir_url = NEXTCLOUD_URL.format(user=user, path=current_path.lstrip("/"))
        res = requests.request("MKCOL", dir_url, auth=(user, password))
        if res.status_code in (201, 405):  # 201 = erstellt, 405 = existiert schon
            continue
        elif res.status_code != 301:  # manchmal folgt ein Redirect
            print(f"[WARN] MKCOL {current_path} failed:", res.status_code, res.text)

    # Datei hochladen
    with open(local_path, "rb") as f:
        res = requests.put(url, auth=(user, password), data=f)
    if res.status_code in (200, 201, 204):
        print("[OK] Uploaded to Nextcloud:", remote_path)
        return url
    else:
        print("[ERROR] Upload failed:", res.status_code, res.text)
        return None

def download_from_nextcloud(season, filename, local_path):
    user, password = NEXTCLOUD_AUTH
    remote_path = f"Power-Ladys/Scores/S{season}/{filename}"
    url = NEXTCLOUD_URL.format(user=user, path=remote_path)
    print("[DEBUG] Downloading from:", url)

    curl_cmd = [
        "curl", "-s", "-u", f"{user}:{password}", "-H", "Cache-Control: no-cache", "-o", str(local_path), url
    ]
    result = subprocess.run(curl_cmd, capture_output=True)
    if result.returncode == 0:
        print("[OK] Downloaded updated file from Nextcloud")
    else:
        print("[ERROR] curl failed:", result.stderr.decode())

def generate_excel(match, players, output_path):
    match_id, match_date, season, opponent, event = match
    event_safe = event.replace(" ", "_")
    opponent_safe = opponent.replace(" ", "_")
    filename = f"{match_id}_{event_safe}_{opponent_safe}.xlsx"
    folder = output_path / f"S{season}"
    filepath = folder / filename

    if filepath.exists():
        print("[INFO] Local file already exists:", filepath)
    else:
        folder.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        ws = wb.active
        ws.title = "Match Info"

        ws.append([f"Match ID: {match_id}", f"Date: {match_date}", f"Season: {season}", f"Opponent: {opponent}", f"Event: {event}"])
        headers = ["MatchID", "PlayerID", "Player", "Score", "Points"]
        ws.append(headers)

        for pid, name in players:
            ws.append([match_id, pid, name, "", ""])

        wb.save(filepath)
        print("[OK] Created local file:", filepath)

    remote_path = str((NEXTCLOUD_BASE / f"S{season}" / filename)).replace("\\", "/")
    upload_url = upload_to_nextcloud(filepath, remote_path)
    web_url = f"http://cloud-pl.de?path=/Scores/S{season}/{filename}"
    return web_url

def import_excel_to_matchscore(match_id):
    with sqlite3.connect(DB_PATH) as conn:
        match = get_match_info(conn, match_id)
        if not match:
            print("[ERROR] No match found with ID", match_id)
            return
        _, _, season, opponent, event = match
        filename = f"{match_id}_{event.replace(' ', '_')}_{opponent.replace(' ', '_')}.xlsx"
        local_path = Path("tmp") / f"{filename}"
        tsv_path = Path("tmp") / f"sheet_{match_id}.tsv"

        tsv_path.parent.mkdir(parents=True, exist_ok=True)
        download_from_nextcloud(season, filename, local_path)

        from openpyxl import load_workbook
        wb = load_workbook(filename=local_path, data_only=True)
        ws = wb.active

        with open(tsv_path, "w", encoding="utf-8") as f:
            for i, row in enumerate(ws.iter_rows(min_row=3, values_only=True), start=3):
                print(f"[DEBUG] Row {i}: {row}")
                if not row or len(row) < 5:
                    print(f"[WARN] Skipping row {i}: {row}")
                    continue
                mid, pid, _, score, points = row
                try:
                    score = int(score) if score not in (None, "") else 0
                except Exception:
                    print(f"[WARN] Invalid score in row {i}: {score}")
                    score = 0
                try:
                    points = int(points) if points not in (None, "") else 0
                except Exception:
                    print(f"[WARN] Invalid points in row {i}: {points}")
                    points = 0
                if not pid:
                    print(f"[WARN] Missing player ID in row {i}: {row}")
                    continue
                f.write(f"{mid}\t{pid}\t{score}\t{points}\n")

        print("[OK] TSV created:", tsv_path)

        imported = 0
        with open(tsv_path, encoding="utf-8") as f:
            for line in f:
                mid, player_id, score, points = line.strip().split("\t")
                cmd = ["python", "hcr2.py", "matchscore", "add", mid, player_id, score, points]
                result = subprocess.run(cmd, capture_output=True, text=True)
                print(result.stdout.strip())
                if result.returncode == 0:
                    imported += 1
                else:
                    print(result.stderr.strip())

        print("[OK] Imported", imported, "entries from", tsv_path)

def print_help():
    print("Usage: python hcr2.py sheet <command> <match_id>")
    print("\nCommands:")
    print("  create <match_id>   Create Excel file for the match and upload to Nextcloud")
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
                print("[ERROR] No match found with ID", match_id)
                return
            players = get_active_players(conn)
            url = generate_excel(match, players, output_path=NEXTCLOUD_BASE)
            print("[OK] Done:", url if url else "No URL returned")

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

