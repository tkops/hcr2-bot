import sqlite3
import os
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from pathlib import Path
import sys
import requests
from secrets_config import NEXTCLOUD_AUTH

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
        SELECT name FROM players
        WHERE active = 1 AND team = 'PLTE'
        ORDER BY name
    """)
    return [row[0] for row in c.fetchall()]


def upload_to_nextcloud(local_path, remote_path):
    user, password = NEXTCLOUD_AUTH
    remote_path = str(remote_path).lstrip("/")  # Entfernt führenden Slash
    url = NEXTCLOUD_URL.format(user=user, path=remote_path)

    res = requests.head(url, auth=(user, password))
    if res.status_code == 200:
        print(f"☁️ File already exists in Nextcloud: {remote_path}")
        return url

    with open(local_path, "rb") as f:
        res = requests.put(url, auth=(user, password), data=f)
    if res.status_code in (200, 201, 204):
        print(f"☁️ Uploaded to Nextcloud: {remote_path}")
        return url
    else:
        print(f"❌ Upload failed: {res.status_code} {res.text}")
        return None


def generate_excel(match, players, output_path):
    match_id, match_date, season, opponent, event = match
    event_safe = event.replace(" ", "_")
    opponent_safe = opponent.replace(" ", "_")
    filename = f"{match_id}_{event_safe}_{opponent_safe}.xlsx"
    folder = output_path / f"S{season}"
    filepath = folder / filename

    if filepath.exists():
        print(f"🔁 Local file already exists: {filepath}")
    else:
        folder.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        ws = wb.active
        ws.title = "Match Info"

        ws.cell(row=1, column=1, value=f"Match ID: {match_id}")
        ws.cell(row=1, column=2, value=f"Date: {match_date}")
        ws.cell(row=1, column=3, value=f"Season: {season}")
        ws.cell(row=1, column=4, value=f"Opponent: {opponent}")
        ws.cell(row=1, column=5, value=f"Event: {event}")

        headers = ["MatchID", "Player", "Score", "Points", "Copy"]
        for i, header in enumerate(headers, start=1):
            ws.cell(row=2, column=i, value=header)

        for idx, player in enumerate(players, start=3):
            ws.cell(row=idx, column=1, value=match_id)
            ws.cell(row=idx, column=2, value=player)
            formula = f"=A{idx}&\";\"&B{idx}&\";\"&C{idx}&\";\"&D{idx}"
            ws.cell(row=idx, column=5, value=formula)

        wb.save(filepath)
        print(f"📄 Created local file: {filepath}")

    remote_path = str((NEXTCLOUD_BASE / f"S{season}" / filename)).replace("\\", "/")
    upload_url = upload_to_nextcloud(filepath, remote_path)
    web_url = f"http://cloud-pl.de?path=/Scores/S{season}/{filename}"
    return web_url


def print_help():
    print("Usage: python hcr2.py sheet create <match_id>")
    print("\nCommands:")
    print("  create <match_id>   Create Excel file for the match and upload to Nextcloud")


def handle_command(command, args):
    if command == "create":
        if len(args) != 1:
            print("Usage: python hcr2.py sheet create <match_id>")
            return
        try:
            match_id = int(args[0])
        except ValueError:
            print("❌ Match ID must be an integer.")
            return

        with sqlite3.connect(DB_PATH) as conn:
            match = get_match_info(conn, match_id)
            if not match:
                print(f"❌ No match found with ID {match_id}")
                return
            players = get_active_players(conn)
            url = generate_excel(match, players, output_path=NEXTCLOUD_BASE)
            print(f"✅ Done: {url if url else 'No URL returned'}")
    else:
        print(f"❌ Unknown command: {command}")
        print_help()

