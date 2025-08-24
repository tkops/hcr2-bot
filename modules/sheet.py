import sqlite3
from typing import Optional, List, Tuple
import re
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment
from pathlib import Path
from secrets_config import NEXTCLOUD_AUTH
import subprocess
from datetime import datetime, date

DB_PATH = "../hcr2-db/hcr2.db"
NEXTCLOUD_BASE = Path("Power-Ladys-Scores")
NEXTCLOUD_URL = "http://192.168.178.101:8080/remote.php/dav/files/{user}/{path}"

# --- Regex zum Parsen der neuen Player-ID aus der player add-Ausgabe ---
ID_RE = re.compile(r"\bID\s*:\s*(\d+)", re.IGNORECASE)


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
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        pass
    try:
        return datetime.strptime(s, "%d.%m.%Y").date()
    except Exception:
        return None


def _is_absent_on(match_day: date, frm: Optional[str], until: Optional[str]) -> bool:
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
    remote_path = f"Power-Ladys-Scores/S{season}/{filename}"
    url = NEXTCLOUD_URL.format(user=user, path=remote_path)
    curl_cmd = ["curl", "-s", "-u", f"{user}:{password}", "-H", "Cache-Control: no-cache", "-o", str(local_path), url]
    subprocess.run(curl_cmd, capture_output=True)


# -------------------- Ranking-Logik --------------------

def _fetch_season_rows(conn: sqlite3.Connection, season_number: int):
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
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, away_from, away_until
        FROM players
        WHERE active = 1 AND team = 'PLTE'
    """)
    base_players = cur.fetchall()
    if not base_players:
        return []
    id_to_player = {pid: (pid, name, a_from, a_until) for (pid, name, a_from, a_until) in base_players}

    rows = _fetch_season_rows(conn, season_number)

    scores_by_match = {}
    for pid, name, team, active, score, match_id, tracks in rows:
        if team != "PLTE" or not active:
            continue
        if score is None:
            continue
        scaled = score * 4 / tracks if tracks else score
        scores_by_match.setdefault(match_id, []).append((pid, scaled))

    import statistics
    player_deltas, player_counts = {}, {}
    for _, entries in scores_by_match.items():
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

    with_scores, without_scores = [], []
    for pid, (pid_, name, a_from, a_until) in id_to_player.items():
        deltas = player_deltas.get(pid)
        if deltas:
            avg_delta = round(sum(deltas) / len(deltas))
            cnt = player_counts.get(pid, 0)
            with_scores.append((avg_delta, -cnt, name.lower(), (pid_, name, a_from, a_until)))
        else:
            without_scores.append((name.lower(), (pid_, name, a_from, a_until)))

    with_scores_sorted = [p for _, _, _, p in sorted(with_scores, key=lambda x: (x[0], x[1], x[2]), reverse=True)]
    without_scores_sorted = [p for _, p in sorted(without_scores, key=lambda x: x[0])]
    return with_scores_sorted + without_scores_sorted


# -------------------- Excel-Generierung & Import --------------------

def generate_excel(match, players, output_path):
    """
    players: (id, name, away_from, away_until) – in Zielreihenfolge.
    Spalten:
      A: MatchID | B: PlayerID | C: Player | D: Score | E: Points | F: Absent | G: Checkin | H: Hinweise
    """
    match_id, match_date_str, season, opponent, event = match

    md = _parse_date_or_none(match_date_str) or date(1970, 1, 1)

    safe_event = sanitize_filename(event)
    safe_opponent = sanitize_filename(opponent)
    filename = f"{match_id}_{safe_event}_{safe_opponent}.xlsx"
    folder = output_path / f"S{season}"
    filepath = folder / filename

    folder.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Match Info"

    # Kopfzeile + Header
    ws.append([f"Match ID: {match_id}", f"Date: {match_date_str}", f"Season: {season}", f"Opponent: {opponent}", f"Event: {event}"])
    ws.append(["MatchID", "PlayerID", "Player", "Score", "Points", "Absent", "Checkin", "Hinweise"])

    # Spaltenbreiten
    ws.column_dimensions["A"].width = 15
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 26
    ws.column_dimensions["D"].width = 20
    ws.column_dimensions["E"].width = 20
    ws.column_dimensions["F"].width = 8
    ws.column_dimensions["G"].width = 9
    ws.column_dimensions["H"].width = 120




    # Hinweise
    ws["H2"] = (
        "H1: Nicht gefahren → Score=0 und Points=0 eintragen.\n"
        "H2: Absent true, wenn ein Spieler entschuldigt ist (Urlaub etc.)\n"
        "H3: Checkin true, wenn Spieler sich ins Match eingeloghgt hat aber nicht gefahren ist\n"
        "H4: Falls ein Spieler das Team verlassen hat aber noch in der Liste steht, Zeile einfach löschen\n"
        "H5: Sollte ein Spieler fehlen, kann er einfach mit richtiger ID hinzugefügt werden\n"
        "H6: Sollte ein Spieler fehlen, der noch nicht angelegt wurde, dann statt der der ID ein 'a' für add in Spalte B. Spieler wird dann beim Import  angelegt"
    )
    ws["H2"].alignment = Alignment(wrap_text=True, vertical="top")


    # Datenzeilen
    for pid, name, a_from, a_until in players:
        absent_flag = _is_absent_on(md, a_from, a_until)
        ws.append([match_id, pid, name, "", "", "true" if absent_flag else "false", "", ""])

    # A/B zentrieren (alle Zeilen)
    align_center = Alignment(horizontal="center", vertical="center")
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=2):
        for cell in row:
            cell.alignment = align_center

    wb.save(filepath)

    remote_path = NEXTCLOUD_BASE / f"S{season}" / filename
    upload_to_nextcloud(filepath, remote_path)

    try:
        filepath.unlink()
    except Exception:
        pass

    web_url = f"https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path=/Scores/S{season}"
    return f"[{filename}]({web_url})", True


# --- Helfer: Player-ID aus Spalte B interpretieren ---
def _parse_pid_marker(pid_cell):
    """
    ('SKIP', None)   -> leere PlayerID: ganze Zeile ignorieren
    ('CREATE', None) -> 'a', 'add', 'new', '+', 'none', '-'
    ('OK', pid:int)  -> gültige numerische ID
    ('ERROR', msg)   -> harter Fehlertext
    """
    if pid_cell is None:
        return ("SKIP", None)

    if isinstance(pid_cell, float) and float(pid_cell).is_integer():
        return ("OK", int(pid_cell))
    if isinstance(pid_cell, int):
        return ("OK", int(pid_cell))

    s = str(pid_cell).strip().lower()
    if s == "":
        return ("SKIP", None)
    if s in ("a", "add", "new", "+", "none", "-"):
        return ("CREATE", None)
    if s.isdigit():
        return ("OK", int(s))

    return ("ERROR", f"invalid playerID '{pid_cell}' – use a number or 'a'")


# --- Helfer: Spieler anlegen und vergebene ID zurückgeben ---
def _add_player_plte_and_get_id(name: str) -> Optional[int]:
    name = (name or "").strip()
    if not name:
        return None
    # Spieler ohne Alias anlegen (Alias generiert player.py automatisch)
    cmd = ["python", "hcr2.py", "player", "add", "PLTE", name]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return None

    if res.returncode != 0:
        return None

    out = (res.stdout or "") + "\n" + (res.stderr or "")
    # Erwartete Ausgabe enthält z.B. "ID: 123"
    m = ID_RE.search(out)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass

    # Fallback: letzte Zahl in der Ausgabe nehmen (vorsichtig)
    fallback = re.findall(r"\b(\d{1,9})\b", out)
    if fallback:
        try:
            return int(fallback[-1])
        except Exception:
            return None
    return None


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

        # ---------- Einlesen + Plausi-Checks ----------
        errors = []
        entries = []  # dicts: {'row': r, 'pid': pid, 'score': s, 'points': p, 'absent': a, 'checkin': c}

        def strict_int(cell_val, label, row_idx):
            # Pflichtfeld: keine Leere, kein Text-Müll, nur ganze Zahlen
            if cell_val is None or (isinstance(cell_val, str) and cell_val.strip() == ""):
                errors.append(f"Row {row_idx}: {label} must not be empty.")
                return None
            if isinstance(cell_val, float):
                if cell_val.is_integer():
                    return int(cell_val)
                errors.append(f"Row {row_idx}: {label} must be an integer, got float={cell_val}.")
                return None
            if isinstance(cell_val, int):
                return cell_val
            if isinstance(cell_val, str):
                s = cell_val.strip()
                if s.isdigit():
                    return int(s)
                errors.append(f"Row {row_idx}: {label} must be a number, got '{cell_val}'.")
                return None
            # other types
            errors.append(f"Row {row_idx}: {label} has invalid type {type(cell_val).__name__}.")
            return None

        def to_bool01(x):
            if x is None:
                return 0
            s = str(x).strip().lower()
            if s in ("1", "true", "yes", "y", "ja"):
                return 1
            if s in ("0", "false", "no", "n", "nein", ""):
                return 0
            return 0

        # Sammle alle Zeilen (ab Zeile 3 oder 4 – durch SKIP robust gegenüber Leerzeilen)
        row_idx = 3
        for row in ws.iter_rows(min_row=3, values_only=True):
            # Row: A..H → MatchID, PlayerID, Player, Score, Points, Absent, Checkin, Hinweise
            if not row or len(row) < 3:
                row_idx += 1
                continue

            mid = row[0]
            pid_cell = row[1]
            player_name_cell = row[2]

            # PlayerID interpretieren
            mode, pid_or_msg = _parse_pid_marker(pid_cell)
            if mode == "SKIP":
                row_idx += 1
                continue
            if mode == "ERROR":
                errors.append(f"Row {row_idx}: {pid_or_msg}")
                row_idx += 1
                continue
            if mode == "CREATE":
                name = (player_name_cell or "").strip()
                if not name:
                    errors.append(f"Row {row_idx}: cannot create player – column C (Player) is empty.")
                    row_idx += 1
                    continue
                new_id = _add_player_plte_and_get_id(name)
                if not new_id:
                    errors.append(f"Row {row_idx}: failed to create player '{name}'.")
                    row_idx += 1
                    continue
                pid = int(new_id)
            else:  # OK
                pid = int(pid_or_msg)

            score_cell   = row[3] if len(row) >= 4 else None
            points_cell  = row[4] if len(row) >= 5 else None
            absent_raw   = row[5] if len(row) >= 6 else "false"
            checkin_raw  = row[6] if len(row) >= 7 else "false"

            # Pflichtfelder prüfen
            score_val  = strict_int(score_cell,  "Score",  row_idx)
            points_val = strict_int(points_cell, "Points", row_idx)

            # Range
            if score_val is not None and not (0 <= score_val <= 75000):
                errors.append(f"Row {row_idx}: Score out of range (0..75000): {score_val}")
            if points_val is not None and not (0 <= points_val <= 300):
                errors.append(f"Row {row_idx}: Points out of range (0..300): {points_val}")

            # Absent/Checkin
            absent01  = to_bool01(absent_raw)
            checkin01 = to_bool01(checkin_raw)

            if score_val is not None and points_val is not None:
                entries.append({
                    "row": row_idx,
                    "pid": int(pid),
                    "score": int(score_val),
                    "points": int(points_val),
                    "absent": int(absent01),
                    "checkin": int(checkin01),
                })

            row_idx += 1

        # High Points > 20 dürfen nicht doppelt vorkommen
        seen_high = {}
        for e in entries:
            p = e["points"]
            if p > 20:
                seen_high.setdefault(p, []).append(e)
        for pval, rows_dup in seen_high.items():
            if len(rows_dup) > 1:
                ids = ", ".join(f"row {r['row']} (pid {r['pid']})" for r in rows_dup)
                errors.append(f"High points duplicated (>20): {pval} appears in {ids}")

        # Monotonie: Sortiere nach Score DESC; Points müssen non-increasing sein;
        # Gleichstand bei Points nur erlaubt, wenn beide Points < 20.
        entries_sorted = sorted(entries, key=lambda x: (-x["score"], x["pid"]))
        for i in range(len(entries_sorted) - 1):
            a = entries_sorted[i]
            b = entries_sorted[i + 1]
            # a hat >= Score von b
            if a["points"] < b["points"]:
                errors.append(
                    f"Monotony violation: row {a['row']} (score {a['score']}, points {a['points']}) "
                    f"vs row {b['row']} (score {b['score']}, points {b['points']})"
                )
            if a["points"] == b["points"] and a["points"] >= 20:
                errors.append(
                    f"Equal high points not allowed (>=20): rows {a['row']} & {b['row']} both {a['points']}"
                )

        # Falls Fehler → abbrechen
        if errors:
            print("❌ Import aborted due to validation errors:")
            for msg in errors:
                print(" -", msg)
            return

        # ---------- TSV schreiben + an matchscore weiterreichen ----------
        with open(tsv_path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(f"{match_id}\t{e['pid']}\t{e['score']}\t{e['points']}\t{e['absent']}\t{e['checkin']}\n")

        imported = 0
        changed = 0
        with open(tsv_path, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 6:
                    parts = parts + ["0"]
                mid, player_id, score, points, absent01, checkin01 = parts[:6]
                cmd = [
                    "python", "hcr2.py", "matchscore", "add",
                    mid, player_id, score, points, absent01, checkin01
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    imported += 1
                    out = (result.stdout or "").upper()
                    if "UNCHANGED" in out:
                        pass
                    elif "CHANGED" in out:
                        changed += 1

        for path in (local_path, tsv_path):
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

            _, _, season, _, _ = match
            ranked_players = rank_active_plte_for_season(conn, season) or get_active_players(conn)

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

