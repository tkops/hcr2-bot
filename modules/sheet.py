#!/usr/bin/env python3
import sqlite3
from typing import Optional, List, Tuple
import re
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from pathlib import Path
from secrets_config import NEXTCLOUD_AUTH
import subprocess
from datetime import datetime, date
from modules.common import DB_PATH, connect_db, is_absent_on, parse_date_or_none, parse_int
NEXTCLOUD_BASE = Path("Power-Ladys-Scores")
NEXTCLOUD_URL = "http://192.168.178.101:8080/remote.php/dav/files/{user}/{path}"

# --- Columns that are not exported/imported ---
EXCLUDED_PLAYER_COLS = {
    "created_at",
    "team",
    "away_from",
    "away_until",
    "active_modified",
    "about",
    "preferred_vehicles",
    "playstyle",
    "language",
    "country_code",
    "last_modified",
}

# --- Regex for parsing the new player ID from player add output ---
ID_RE = re.compile(r"\bID\s*:\s*(\d+)", re.IGNORECASE)

# --- Player export/import targets ---
PLAYERS_XLSX_NAME = "Ladys.xlsx"
PLAYERS_REMOTE_PATH = NEXTCLOUD_BASE / PLAYERS_XLSX_NAME
PLAYERS_LOCAL_TMP = Path("tmp") / PLAYERS_XLSX_NAME

# --- Donations export/import targets ---
DONATIONS_XLSX_NAME = "Donations.xlsx"
DONATIONS_REMOTE_PATH = NEXTCLOUD_BASE / DONATIONS_XLSX_NAME
DONATIONS_LOCAL_TMP = Path("tmp") / DONATIONS_XLSX_NAME


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


def _is_absent_on(match_day: date, frm: Optional[str], until: Optional[str]) -> bool:
    return is_absent_on(match_day, frm, until)


def upload_to_nextcloud(local_path, remote_path, *, overwrite: bool = False):
    """
    Upload to Nextcloud.
    - overwrite=False (default): create only, do not overwrite.
    - overwrite=True: overwrite an existing file (PUT).
    Returns: (url, created_flag); created_flag=True only when newly created.
    """
    import requests
    user, password = NEXTCLOUD_AUTH
    remote_path = str(remote_path).lstrip("/")
    url = NEXTCLOUD_URL.format(user=user, path=remote_path)

    # Check existence for the created/updated flag.
    try:
        head = requests.head(url, auth=(user, password))
        exists = (head.status_code == 200)
    except Exception:
        exists = False

    if exists and not overwrite:
        # Do nothing; do not overwrite.
        return url, False

    # Create the folder chain idempotently.
    parts = remote_path.split("/")[:-1]
    current_path = ""
    for part in parts:
        current_path += f"/{part}"
        dir_url = NEXTCLOUD_URL.format(user=user, path=current_path.lstrip("/"))
        requests.request("MKCOL", dir_url, auth=(user, password))

    # Upload; PUT overwrites if present.
    with open(local_path, "rb") as f:
        res = requests.put(url, auth=(user, password), data=f)

    if res.status_code in (200, 201, 204):
        return url, (not exists)  # True when new, False when overwritten.
    return None, False


def delete_from_nextcloud(remote_path) -> bool:
    """
    Delete a file in Nextcloud via WebDAV DELETE. Return True on success.
    """
    import requests
    user, password = NEXTCLOUD_AUTH
    url = NEXTCLOUD_URL.format(user=user, path=str(remote_path).lstrip("/"))
    try:
        r = requests.delete(url, auth=(user, password))
        return r.status_code in (200, 204)
    except Exception:
        return False


def download_from_nextcloud(season, filename, local_path):
    user, password = NEXTCLOUD_AUTH
    remote_path = f"Power-Ladys-Scores/S{season}/{filename}"
    url = NEXTCLOUD_URL.format(user=user, path=remote_path)
    curl_cmd = ["curl", "-s", "-u", f"{user}:{password}", "-H", "Cache-Control: no-cache", "-o", str(local_path), url]
    subprocess.run(curl_cmd, capture_output=True)


# -------------------- Ranking Logic --------------------

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


# -------------------- Excel Generation & Import (Match Sheet) --------------------

def generate_excel(match, players, output_path):
    """
    Match sheet. Unchanged except for standard formatting.
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

    ws.append([f"Match ID: {match_id}", f"Date: {match_date_str}", f"Season: {season}", f"Opponent: {opponent}", f"Event: {event}"])

    ws.insert_rows(2, amount=1)
    ws["A2"] = "Result"
    ws["B2"] = "Power Ladies -->"
    ws["C2"] = ""
    ws["D2"] = ""
    ws["E2"] = f"<-- {opponent}"

    ws.append(["MatchID", "PlayerID", "Player", "Score", "Points", "Absent", "Checkin", "Notes"])

    for row in ws.iter_rows(min_row=3, max_row=3, min_col=1, max_col=7):
        for cell in row:
            cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.column_dimensions["A"].width = 15
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 26
    ws.column_dimensions["D"].width = 20
    ws.column_dimensions["E"].width = 20
    ws.column_dimensions["F"].width = 8
    ws.column_dimensions["G"].width = 9
    ws.column_dimensions["H"].width = 130

    ws["H3"] = (
        "H1: Did not drive: enter Score=0 and Points=0.\n"
        "H2: Set Absent to true when a player is excused (vacation etc.).\n"
        "H3: Set Checkin to true when a player logged into the match but did not drive.\n"
        "H4: If a player left the team but is still listed, delete the row.\n"
        "H5: If a player is missing, add them with the correct ID.\n"
        "H6: If a missing player has not been created yet, enter 'a' for add in column B instead of the ID. The player is created during import.\n"
        "H7: Enter the match results in cell C2 (Ladies) and D2 (opponent)."
    )
    ws["H3"].alignment = Alignment(wrap_text=True, vertical="top")

    for pid, name, a_from, a_until in players:
        absent_flag = _is_absent_on(md, a_from, a_until)
        ws.append([match_id, pid, name, "", "", "true" if absent_flag else "false", "", ""])

    align_center = Alignment(horizontal="center", vertical="center")
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=2):
        for cell in row:
            cell.alignment = align_center

    wb.save(filepath)

    remote_path = NEXTCLOUD_BASE / f"S{season}" / filename
    upload_to_nextcloud(filepath, remote_path)  # No overwrite for match sheets.

    try:
        filepath.unlink()
    except Exception:
        pass

    web_url = f"https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path=/Scores/S{season}"
    return f"[{filename}]({web_url})", True


# --- Helpers for match import ---

def _parse_pid_marker(pid_cell):
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


def _add_player_plte_and_get_id(name: str) -> Optional[int]:
    name = (name or "").strip()
    if not name:
        return None
    cmd = ["python", "hcr2.py", "player", "add", "PLTE", name]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    except Exception:
        return None
    if res.returncode != 0:
        return None
    out = (res.stdout or "") + "\n" + (res.stderr or "")
    m = ID_RE.search(out)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    fallback = re.findall(r"\b(\d{1,9})\b", out)
    if fallback:
        try:
            return int(fallback[-1])
        except Exception:
            return None
    return None


# --- Normalization for import comparisons ---
def _norm(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        return s if s != "" else None
    return v


def import_excel_to_matchscore(match_id):
    with sqlite3.connect(DB_PATH) as conn:
        match = get_match_info(conn, match_id)
        if not match:
            print("❌ No match found.")
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

        errors = []
        entries = []

        def strict_int(cell_val, label, row_idx):
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
            errors.append(f"Row {row_idx}: {label} has invalid type {type(cell_val).__name__}.")
            return None

        def read_int_or_none(val):
            if val is None:
                return None
            if isinstance(val, int):
                return val
            if isinstance(val, float) and val.is_integer():
                return int(val)
            if isinstance(val, str):
                s = val.strip()
                if s.isdigit():
                    return int(s)
            return None

        def to_bool01(x):
            if x is None:
                return 0
            s = str(x).strip().lower()
            if s in ("1", "true", "yes", "y", "j\u0061"):
                return 1
            if s in ("0", "false", "no", "n", "n\u0065in", ""):
                return 0
            return 0

        ladyscore = read_int_or_none(ws["C2"].value)
        oppscore  = read_int_or_none(ws["D2"].value)
        if ladyscore is None or oppscore is None:
            errors.append("Row 2: please fill team scores in C2 (Power Ladies) and D2 (Opponent).")

        row_idx = 4
        for row in ws.iter_rows(min_row=4, values_only=True):
            if not row or len(row) < 3:
                row_idx += 1
                continue

            pid_cell = row[1]
            player_name_cell = row[2]

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
            else:
                pid = int(pid_or_msg)

            score_cell   = row[3] if len(row) >= 4 else None
            points_cell  = row[4] if len(row) >= 5 else None
            absent_raw   = row[5] if len(row) >= 6 else "false"
            checkin_raw  = row[6] if len(row) >= 7 else "false"

            score_val  = strict_int(score_cell,  "Score",  row_idx)
            points_val = strict_int(points_cell, "Points", row_idx)

            if score_val is not None and not (0 <= score_val <= 75000):
                errors.append(f"Row {row_idx}: Score out of range (0..75000): {score_val}")
            if points_val is not None and not (0 <= points_val <= 300):
                errors.append(f"Row {row_idx}: Points out of range (0..300): {points_val}")

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

        seen_high = {}
        for e in entries:
            p = e["points"]
            if p > 20:
                seen_high.setdefault(p, []).append(e)
        for pval, rows_dup in seen_high.items():
            if len(rows_dup) > 1:
                ids = ", ".join(f"row {r['row']} (pid {r['pid']})" for r in rows_dup)
                errors.append(f"High points duplicated (>20): {pval} appears in {ids}")

        entries_sorted = sorted(entries, key=lambda x: (-x["score"], x["pid"]))
        for i in range(len(entries_sorted) - 1):
            a = entries_sorted[i]
            b = entries_sorted[i + 1]
            if a["points"] < b["points"]:
                errors.append(
                    f"Monotony violation: row {a['row']} (score {a['score']}, points {a['points']}) "
                    f"vs row {b['row']} (score {b['score']}, points {b['points']})"
                )
            if a["points"] == b["points"] and a["points"] >= 20:
                errors.append(
                    f"Equal high points not allowed (>=20): rows {a['row']} & {b['row']} both {a['points']}"
                )

        sum_points = sum(e["points"] for e in entries)
        if ladyscore is not None and sum_points != ladyscore:
            errors.append(f"Team points mismatch: sum(points)={sum_points} != C2={ladyscore}")

        if errors:
            print("❌ Import aborted due to validation errors:")
            for msg in errors:
                print(" -", msg)
            return

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
                    if "CHANGED" in out:
                        changed += 1

        upd_ok = False
        try:
            cmd_upd = [
                "python", "hcr2.py", "match", "edit",
                "--id", str(match_id),
                "--score", str(ladyscore if ladyscore is not None else 0),
                "--scoreopp", str(oppscore if oppscore is not None else 0),
            ]
            upd_res = subprocess.run(cmd_upd, capture_output=True, text=True)
            upd_ok = (upd_res.returncode == 0)
        except Exception:
            upd_ok = False

        for path in (local_path, tsv_path):
            try:
                path.unlink()
            except Exception:
                pass

        web_url = f"https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path=/Scores/S{season}"
        status = "Changed" if changed > 0 else "Unchanged"
        score_status = "Score updated" if upd_ok else "Score update failed"
        print(f"✅ [{filename}]({web_url}) ({status}, {imported} imported, {changed} changed; {score_status})")


# ===================== Players: Export/Import (active PLTE, excludes, formatting) =====================

def _download_players_xlsx(local_path: Path = PLAYERS_LOCAL_TMP) -> Optional[Path]:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    user, password = NEXTCLOUD_AUTH
    url = NEXTCLOUD_URL.format(user=user, path=str(PLAYERS_REMOTE_PATH).lstrip("/"))
    curl_cmd = ["curl", "-s", "-u", f"{user}:{password}", "-H", "Cache-Control: no-cache", "-o", str(local_path), url]
    subprocess.run(curl_cmd, capture_output=True)
    return local_path if local_path.exists() and local_path.stat().st_size > 0 else None


def _upload_players_xlsx(local_path: Path):
    # Only the players workbook may be overwritten.
    return upload_to_nextcloud(local_path, PLAYERS_REMOTE_PATH, overwrite=True)


def _detect_boolean_columns(conn: sqlite3.Connection, table: str, candidate_overrides=None):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    out = set()
    for _, name, ctype, *_ in cur.fetchall():
        t = (ctype or "").upper()
        if "BOOL" in t:
            out.add(name)
    if candidate_overrides:
        out |= set(candidate_overrides)
    return out


def _to_bool01_if_needed(val):
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "y", "j\u0061"):
        return 1
    if s in ("0", "false", "no", "n", "n\u0065in", ""):
        return 0
    if isinstance(val, (int, float)):
        return 1 if int(val) != 0 else 0
    return None


def _autofit_columns(ws, min_w=10, max_w=60):
    # Bold header.
    for cell in ws[1]:
        cell.font = Font(bold=True)
    # Auto width based on content.
    for col_idx, col in enumerate(ws.iter_cols(min_row=1, max_row=ws.max_row,
                                               min_col=1, max_col=ws.max_column),
                                  start=1):
        max_len = 0
        for cell in col:
            v = "" if cell.value is None else str(cell.value)
            if len(v) > max_len:
                max_len = len(v)
        width = max(min_w, min(max_w, max_len + 2))
        ws.column_dimensions[get_column_letter(col_idx)].width = width


def export_players_to_excel(db_path: str = DB_PATH, out_path: Path = PLAYERS_LOCAL_TMP):
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(players)")
        cols_info = cur.fetchall()
        if not cols_info:
            print("❌ players table not found")
            return
        all_columns = [c[1] for c in cols_info]
        export_columns = [c for c in all_columns if c not in EXCLUDED_PLAYER_COLS]

        cur.execute(f"""
            SELECT {', '.join(export_columns)}
            FROM players
            WHERE team = 'PLTE' AND active = 1
            ORDER BY garage_power DESC, name COLLATE NOCASE
        """)
        rows = cur.fetchall()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        ws = wb.active
        ws.title = "players"

        ws.append(export_columns)
        for r in rows:
            ws.append(list(r))

        _autofit_columns(ws, min_w=10, max_w=60)

        wb.save(out_path)

    url, created = _upload_players_xlsx(out_path)
    try:
        out_path.unlink()
    except Exception:
        pass

    web_url = f"https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path=/Scores"
    print(f"✅ [Power-Ladys-Scores/{PLAYERS_XLSX_NAME}]({web_url}) ({'Created' if created else 'Updated'})")


def import_players_from_excel(db_path: str = DB_PATH, local_xlsx: Optional[Path] = None):
    local = local_xlsx or _download_players_xlsx()
    if not local or not local.exists():
        print("❌ players Excel not found on Nextcloud")
        return

    wb = load_workbook(filename=local, data_only=True)
    ws = wb.active

    first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
    header = [str(c) if c is not None else "" for c in (first_row or [])]
    header = [h.strip() for h in header]
    if not header or "id" not in header:
        print("❌ First row must contain column names including 'id'")
        return

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(players)")
        db_cols_info = cur.fetchall()
        db_cols = [c[1] for c in db_cols_info]
        db_cols_set = set(db_cols)

        allowed_import_cols = (db_cols_set - EXCLUDED_PLAYER_COLS) | {"id"}

        bool_cols = _detect_boolean_columns(conn, "players", candidate_overrides={"active", "is_leader"})

        cur.execute("SELECT id FROM players WHERE team='PLTE'")
        existing_ids = {r[0] for r in cur.fetchall()}

        updated = 0
        inserted = 0
        skipped = 0
        errors = 0

        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row:
                continue
            row_map_full = dict(zip(header, row))
            row_map = {k: v for k, v in row_map_full.items() if k in allowed_import_cols}

            if all((v is None or str(v).strip() == "") for v in row_map.values()):
                continue

            rid = row_map.get("id")
            rid_int = None
            if isinstance(rid, float) and rid.is_integer():
                rid_int = int(rid)
            elif isinstance(rid, int):
                rid_int = rid
            elif isinstance(rid, str) and rid.strip().isdigit():
                rid_int = int(rid.strip())

            for b in (set(row_map.keys()) & bool_cols):
                row_map[b] = _to_bool01_if_needed(row_map[b])

            try:
                if rid_int and rid_int in existing_ids:
                    # Candidate columns without id.
                    set_cols = [c for c in row_map.keys() if c != "id"]
                    if not set_cols:
                        skipped += 1
                        continue

                    # Load current DB values.
                    cur.execute(f"SELECT {', '.join(set_cols)} FROM players WHERE id = ?", (rid_int,))
                    db_row = cur.fetchone()
                    if not db_row:
                        skipped += 1
                        continue
                    db_map = {col: db_row[idx] for idx, col in enumerate(set_cols)}

                    # Determine differences.
                    changed_cols = [c for c in set_cols if _norm(row_map[c]) != _norm(db_map.get(c))]
                    if not changed_cols:
                        skipped += 1
                        continue

                    # Set last_modified only when changes exist.
                    now = datetime.now().isoformat(timespec="seconds")
                    placeholders = ", ".join([f"{c}=?" for c in changed_cols] + ["last_modified=?"])
                    values = [row_map[c] for c in changed_cols] + [now, rid_int]
                    cur.execute(f"UPDATE players SET {placeholders} WHERE id = ?", values)
                    updated += 1
                else:
                    # Insert
                    row_map["team"] = "PLTE"
                    if "active" not in row_map or row_map["active"] is None:
                        row_map["active"] = 1

                    insert_cols = [c for c in row_map.keys() if c != "id" and c not in EXCLUDED_PLAYER_COLS]
                    if not insert_cols:
                        skipped += 1
                        continue

                    now = datetime.now().isoformat(timespec="seconds")
                    insert_cols.append("last_modified")
                    placeholders = ", ".join(["?"] * len(insert_cols))
                    values = [row_map[c] for c in insert_cols if c != "last_modified"] + [now]
                    cur.execute(
                        f"INSERT INTO players ({', '.join(insert_cols)}) VALUES ({placeholders})",
                        values,
                    )
                    inserted += 1
            except Exception:
                errors += 1

        conn.commit()

    # Delete local copy on a best-effort basis.
    try:
        local.unlink()
    except Exception:
        pass

    # Delete only the players Excel file in Nextcloud; leave match sheets untouched.
    deleted = delete_from_nextcloud(PLAYERS_REMOTE_PATH)
    status = "deleted" if deleted else "delete failed"

    print(f"✅ players import: {updated} updated, {inserted} inserted, {skipped} skipped, {errors} errors ({status} in Nextcloud)")


# ===================== Donations: Export/Import =====================

def _download_donations_xlsx(local_path: Path = DONATIONS_LOCAL_TMP) -> Optional[Path]:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    user, password = NEXTCLOUD_AUTH
    url = NEXTCLOUD_URL.format(user=user, path=str(DONATIONS_REMOTE_PATH).lstrip("/"))
    curl_cmd = ["curl", "-s", "-u", f"{user}:{password}", "-H", "Cache-Control: no-cache", "-o", str(local_path), url]
    subprocess.run(curl_cmd, capture_output=True)
    return local_path if local_path.exists() and local_path.stat().st_size > 0 else None


def _upload_donations_xlsx(local_path: Path):
    # Donations.xlsx may be overwritten.
    return upload_to_nextcloud(local_path, DONATIONS_REMOTE_PATH, overwrite=True)


def _get_latest_donations(conn: sqlite3.Connection) -> dict:
    """
    Return (date, total) of the latest donation entry for each player_id.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT d.player_id, d.date, d.total
        FROM donation d
        JOIN (
            SELECT player_id, MAX(date) AS max_date
            FROM donation
            GROUP BY player_id
        ) latest
        ON d.player_id = latest.player_id AND d.date = latest.max_date
    """)
    out = {}
    for pid, ddate, total in cur.fetchall():
        out[pid] = (ddate, total)
    return out


def export_donations_to_excel(db_path: str = DB_PATH, out_path: Path = DONATIONS_LOCAL_TMP):
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name
            FROM players
            WHERE active = 1 AND team = 'PLTE'
        """)
        players = cur.fetchall()

        latest = _get_latest_donations(conn)

        # Build rows with "previous" donation total (latest known total)
        rows = []
        for pid, name in players:
            _, total = latest.get(pid, (None, 0))
            prev = int(total or 0)
            rows.append((pid, name, prev))

        # Sort: highest previous donation first, then name
        rows.sort(key=lambda x: (-x[2], (x[1] or "").lower()))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        ws = wb.active
        ws.title = "donations"

        today_str = date.today().isoformat()

        # Header.
        ws["A1"] = "Date:"
        ws["A2"] = today_str

        # Header starting at row 3.
        ws["A3"] = "id"
        ws["B3"] = "name"
        ws["C3"] = "donation (k)"
        ws["D3"] = "previous (k)"  # info only

        for cell in ("A3", "B3", "C3", "D3"):
            ws[cell].font = Font(bold=True)

        # Data rows.
        row_idx = 4
        for pid, name, prev in rows:
            ws.cell(row=row_idx, column=1, value=pid)
            ws.cell(row=row_idx, column=2, value=name)
            ws.cell(row=row_idx, column=3, value="")     # new donation entry (empty)
            ws.cell(row=row_idx, column=4, value=_to_k(prev))   # previous shown in k

            row_idx += 1

        # Format
        ws.column_dimensions["A"].width = 8
        ws.column_dimensions["B"].width = 26
        ws.column_dimensions["C"].width = 12
        ws.column_dimensions["D"].width = 12

        wb.save(out_path)

    url, created = _upload_donations_xlsx(out_path)
    try:
        out_path.unlink()
    except Exception:
        pass

    web_url = f"https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path=/Scores"
    print(f"✅ [Power-Ladys-Scores/{DONATIONS_XLSX_NAME}]({web_url}) ({'Created' if created else 'Updated'})")

def _to_k(val: Optional[int]) -> float:
    """Convert absolute integer amount to k-units (thousands) for display."""
    try:
        return round((int(val or 0)) / 1000.0, 1)
    except Exception:
        return 0.0


def _parse_k_amount(val) -> Optional[int]:
    """
    Parse a donation amount entered in 'k' (thousands) and return absolute int (×1000).
    Accepts: 12, 12.5, '12,5', ' 12.5 ', optionally with trailing 'k' (tolerant).
    """
    if val is None:
        return None

    # numeric cells
    if isinstance(val, int):
        return int(val) * 1000
    if isinstance(val, float):
        return int(round(val * 1000))

    # strings
    if isinstance(val, str):
        s = val.strip().lower()
        if not s:
            return None
        s = s.replace("k", "").strip()         # tolerant, even if user typed "12k"
        s = s.replace(" ", "").replace("_", "")
        s = s.replace(",", ".")                # german decimal comma

        if not re.fullmatch(r"-?\d+(\.\d+)?", s):
            return None

        f = float(s)
        if f < 0:
            return None
        return int(round(f * 1000))

    return None


def import_donations_from_excel(db_path: str = DB_PATH, local_xlsx: Optional[Path] = None):
    local = local_xlsx or _download_donations_xlsx()
    if not local or not local.exists():
        print("❌ donations Excel not found on Nextcloud")
        return

    wb = load_workbook(filename=local, data_only=True)
    ws = wb.active

    # Date from A2.
    raw_date = ws["A2"].value
    if isinstance(raw_date, datetime):
        date_str = raw_date.date().isoformat()
    elif isinstance(raw_date, date):
        date_str = raw_date.isoformat()
    elif isinstance(raw_date, str):
        date_str = raw_date.strip()
    else:
        print("❌ No valid date in cell A2")
        return

    added = 0
    errors = 0

    # Rows from 4 onward: id, name, donation.
    for row in ws.iter_rows(min_row=4, values_only=True):
        if not row:
            continue
        pid_val = row[0]
        donation_val = row[2] if len(row) >= 3 else None

        if pid_val is None:
            continue
        # ID as int.
        pid_int = None
        if isinstance(pid_val, float) and pid_val.is_integer():
            pid_int = int(pid_val)
        elif isinstance(pid_val, int):
            pid_int = pid_val
        elif isinstance(pid_val, str) and pid_val.strip().isdigit():
            pid_int = int(pid_val.strip())
        if pid_int is None:
            errors += 1
            continue

        # donation is entered in k (thousands) -> store absolute (×1000)
        if donation_val is None or (isinstance(donation_val, str) and donation_val.strip() == ""):
            continue  # empty -> ignore
        
        don_int = _parse_k_amount(donation_val)
        if don_int is None:
            errors += 1
            continue


        cmd = [
            "python", "hcr2.py", "donations", "add",
            str(pid_int), date_str, str(don_int)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            added += 1
        else:
            errors += 1

    # Delete local copy.
    try:
        local.unlink()
    except Exception:
        pass

    # Delete the donations Excel file in Nextcloud, same as players.
    deleted = delete_from_nextcloud(DONATIONS_REMOTE_PATH)
    status = "deleted" if deleted else "delete failed"

    print(f"✅ donations import: {added} added, {errors} errors ({status} in Nextcloud)")


# ===================== CLI =====================

USAGE_SHEET_CREATE = "Usage: sheet create <match_id>"
USAGE_SHEET_IMPORT = "Usage: sheet import <match_id>"
USAGE_SHEET_PLAYER = "Usage: sheet player <export|import>"
USAGE_SHEET_DONATIONS = "Usage: sheet donations <export|import>"

def print_help():
    print("Usage: python hcr2.py sheet <command> [args]")
    print("\nCommands:")
    print("  create <match_id>        Create one Excel file and upload it to Nextcloud")
    print("  import <match_id>        Import scores from one Excel file on Nextcloud")
    print("  player export            Export active PLTE players to Ladys.xlsx")
    print("  player import            Import active PLTE players from Ladys.xlsx")
    print("  donations export         Export donations sheet for active PLTE players")
    print("  donations import         Import donations from Donations.xlsx")


def handle_command(command, args):
    handlers = {
        "create": _handle_create,
        "import": _handle_import,
        "player": _handle_player,
        "donations": _handle_donations,
    }
    handler = handlers.get(command)
    if handler is None:
        print(f"❌ Unknown sheet command: {command}")
        print_help()
        return
    handler(args)


def _parse_match_id_arg(args, usage: str):
    if len(args) != 1:
        print(usage)
        return None
    match_id = parse_int(args[0], default=None)
    if match_id is None:
        print("❌ Match ID must be an integer.")
        return None
    return match_id


def _handle_create(args):
    match_id = _parse_match_id_arg(args, USAGE_SHEET_CREATE)
    if match_id is None:
        return

    with connect_db() as conn:
        match = get_match_info(conn, match_id)
        if not match:
            print("❌ No match found.")
            return

        _, _, season, _, _ = match
        ranked_players = rank_active_plte_for_season(conn, season) or get_active_players(conn)

    url, uploaded = generate_excel(match, ranked_players, output_path=NEXTCLOUD_BASE)
    print(f"✅ {url} ({'Created' if uploaded else 'Already existed'})")


def _handle_import(args):
    match_id = _parse_match_id_arg(args, USAGE_SHEET_IMPORT)
    if match_id is None:
        return
    import_excel_to_matchscore(match_id)


def _handle_player(args):
    if not args:
        print(USAGE_SHEET_PLAYER)
        return
    sub = args[0]
    if sub == "export":
        export_players_to_excel()
    elif sub == "import":
        import_players_from_excel()
    else:
        print(USAGE_SHEET_PLAYER)


def _handle_donations(args):
    if not args:
        print(USAGE_SHEET_DONATIONS)
        return
    sub = args[0]
    if sub == "export":
        export_donations_to_excel()
    elif sub == "import":
        import_donations_from_excel()
    else:
        print(USAGE_SHEET_DONATIONS)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2 or sys.argv[1] != "sheet":
        print_help()
    else:
        handle_command(sys.argv[2] if len(sys.argv) > 2 else "", sys.argv[3:])
