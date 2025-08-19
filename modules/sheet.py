import sqlite3
from typing import Optional, List, Tuple
import os
import re
from openpyxl import Workbook, load_workbook
from pathlib import Path
import sys
from secrets_config import NEXTCLOUD_AUTH
import subprocess
from datetime import datetime, date

DB_PATH = "db/hcr2.db"
NEXTCLOUD_BASE = Path("Power-Ladys-Scores")  # Upload-Ziel (Ordnerstruktur bleibt darunter S{season}/...)
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


def get_active_players(conn) -> List[Tuple[int, str, Optional[str], Optional[str]]]:
    """
    Holt aktive PLTE-Spieler inkl. Abwesenheitsfenster.
    Rückgabe: [(id, name, away_from, away_until), ...]
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
    # Beachte: Download-Pfad bleibt wie gehabt unter "Power-Ladys/Scores"
    remote_path = f"Power-Ladys/Scores/S{season}/{filename}"
    url = NEXTCLOUD_URL.format(user=user, path=remote_path)

    curl_cmd = [
        "curl", "-s", "-u", f"{user}:{password}", "-H", "Cache-Control: no-cache", "-o", str(local_path), url
    ]
    subprocess.run(curl_cmd, capture_output=True)


# -------------------- Ranking-Logik für Sheet-Reihenfolge --------------------

def _fetch_season_rows(conn: sqlite3.Connection, season_number: int):
    """
    Lädt alle Scores der Season mit nötigen Joins.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT
            ms.player_id,
            p.name,
            p.team,
            p.active,
            ms.score,
            m.id,
            t.tracks
        FROM matchscore ms
        JOIN players p ON ms.player_id = p.id
        JOIN match m ON ms.match_id = m.id
        JOIN teamevent t ON m.teamevent_id = t.id
        WHERE m.season_number = ?
    """, (season_number,))
    return cur.fetchall()


def rank_active_plte_for_season(conn: sqlite3.Connection, season_number: int) -> List[Tuple[int, str, Optional[str], Optional[str]]]:
    """
    Ermittelt die Reihenfolge ALLER aktiven PLTE-Spieler für die gegebene Season.
    - Metrik: Ø(Score-Delta ggü. Median pro Match), Score wird auf 4 Tracks skaliert
    - Kein 80%-Filter
    - Spieler ohne Scores: alphabetisch ans Ende

    Rückgabe: Liste [(id, name, away_from, away_until), ...] in Ziel-Reihenfolge.
    """
    # Basis: aktive PLTE + Abwesenheitsdaten
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, away_from, away_until
        FROM players
        WHERE active = 1 AND team = 'PLTE'
    """)
    base_players = cur.fetchall()  # [(id, name, away_from, away_until), ...]
    if not base_players:
        return []

    id_to_player = {pid: (pid, name, a_from, a_until) for (pid, name, a_from, a_until) in base_players}

    # Rohdaten der Season
    rows = _fetch_season_rows(conn, season_number)

    # Pro Match sammeln (nur aktive PLTE, nur vorhandene Scores)
    scores_by_match = {}
    for pid, name, team, active, score, match_id, tracks in rows:
        if team != "PLTE" or not active:
            continue
        if score is None:
            continue
        scaled = score * 4 / tracks if tracks else score
        scores_by_match.setdefault(match_id, []).append((pid, scaled))

    # Delta ggü. Median je Match
    import statistics
    player_deltas = {}
    player_counts = {}
    for match_id, entries in scores_by_match.items():
        vals = [s for _, s in entries]
        if not vals:
            continue
        try:
            med = statistics.median(vals)
        except statistics.StatisticsError:
            continue
        for pid, s in entries:
            delta = s - med
            player_deltas.setdefault(pid, []).append(delta)
            player_counts[pid] = player_counts.get(pid, 0) + 1

    with_scores = []
    without_scores = []
    for pid, (pid_, name, a_from, a_until) in id_to_player.items():
        deltas = player_deltas.get(pid)
        if deltas:
            avg_delta = round(sum(deltas) / len(deltas))
            cnt = player_counts.get(pid, 0)
            with_scores.append((avg_delta, -cnt, name.lower(), (pid_, name, a_from, a_until)))
        else:
            without_scores.append((name.lower(), (pid_, name, a_from, a_until)))

    # Sortierung:
    # - mit Scores: avg_delta DESC, bei Gleichstand mehr Matches zuerst (deshalb -cnt), dann Name
    with_scores_sorted = [p for _, _, _, p in sorted(with_scores, key=lambda x: (x[0], x[1], x[2]), reverse=True)]
    # - ohne Scores: alphabetisch
    without_scores_sorted = [p for _, p in sorted(without_scores, key=lambda x: x[0])]

    return with_scores_sorted + without_scores_sorted


# -------------------- Excel-Generierung & Import --------------------

def generate_excel(match, players, output_path):
    """
    players: Liste von Tupeln (id, name, away_from, away_until) – bereits in Zielreihenfolge.
    Excel-Spalten:
      A: MatchID
      B: PlayerID
      C: Player
      D: Score
      E: Points
      F: Absent
    """
    match_id, match_date_str, season, opponent, event = match

    # Match-Datum bestimmen (für Abwesenheitsprüfung)
    md = _parse_date_or_none(match_date_str)
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

    # Öffentlicher Web-Ordner (unverändert)
    web_url = f"https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path=/Scores/S{season}"
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
                # Row: MatchID, PlayerID, Player, Score, Points, Absent
                if not row or len(row) < 5 or not row[1]:
                    continue
                mid = row[0]
                pid = row[1]
                score = row[3] if len(row) >= 4 else 0
                points = row[4] if len(row) >= 5 else 0
                absent_raw = row[5] if len(row) >= 6 else "false"

                def _to_bool01(x):
                    if x is None:
                        return 0
                    s = str(x).strip().lower()
                    if s in ("1", "true", "yes", "y", "ja"):
                        return 1
                    if s in ("0", "false", "no", "n", "nein", ""):
                        return 0
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

                f.write(f"{mid}\t{pid}\t{score}\t{points}\t{absent01}\n")

        imported = 0
        changed = 0
        with open(tsv_path, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 5:
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

        web_url = f"https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path=/Scores/S{season}"
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

            # Season aus dem Match nehmen und Ranking ermitteln
            _, _, season, _, _ = match
            ranked_players = rank_active_plte_for_season(conn, season)
            if not ranked_players:
                # Fallback: unsortiert nach Name (sollte selten passieren)
                ranked_players = get_active_players(conn)

            url, uploaded = generate_excel(match, ranked_players, output_path=NEXTCLOUD_BASE)
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

