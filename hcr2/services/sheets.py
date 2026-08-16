from __future__ import annotations

from dataclasses import dataclass, field
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Optional

from hcr2 import timestamps
from hcr2.db import connection as db_connection
from hcr2.integrations import nextcloud
from hcr2.integrations.nextcloud import (
    DONATIONS_DIR,
    LADYS_DIR,
    NEXTCLOUD_BASE,
    delete_file,
    download_file,
    season_subpath,
    upload_file,
)
from hcr2.repositories import matches as match_repo
from hcr2.repositories import players as player_repo
from hcr2.services import matchscores as matchscore_service
from hcr2.services import players as player_service


@dataclass(frozen=True)
class PlayerImportResult:
    updated: int
    inserted: int
    skipped: int
    errors: int
    messages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DonationImportResult:
    added: int
    errors: int
    messages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MatchSheetApplyResult:
    imported: int
    changed: int
    score_updated: bool
    errors: int = 0
    renamed: list[tuple[int, str, str]] = field(default_factory=list)
    rename_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MatchSheetValidationResult:
    entries: list[dict[str, int]]
    errors: list[str]
    name_updates: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PlayerExportData:
    columns: list[str]
    rows: list[tuple]


@dataclass(frozen=True)
class MatchExportData:
    match: tuple[int, str, int, str, str]
    players: list[tuple[int, str, str | None, str | None]]


@dataclass(frozen=True)
class PlayerWorkbookImportOutcome:
    status: str
    result: PlayerImportResult | None = None
    cleanup_status: str | None = None


@dataclass(frozen=True)
class DonationWorkbookImportOutcome:
    status: str
    result: DonationImportResult | None = None
    cleanup_status: str | None = None


@dataclass(frozen=True)
class MatchSheetImportOutcome:
    status: str
    filename: str | None = None
    web_url: str | None = None
    result: MatchSheetApplyResult | None = None
    validation_errors: list[str] | None = None


@dataclass(frozen=True)
class WorkbookExportOutcome:
    status: str
    label: str | None = None
    web_url: str | None = None
    markdown_link: str | None = None
    created: bool = False


PlayerWorkbookReader = Callable[[Path], Any]
DonationWorkbookReader = Callable[[Path], Any]
MatchSheetWorkbookReader = Callable[[Path], Any]
WorkbookBuilder = Callable[..., Any]
WorkbookSaver = Callable[[Any, Path], Path]
AbsentChecker = Callable[..., bool]


PLAYERS_XLSX_NAME = "Ladys.xlsx"
PLAYERS_REMOTE_PATH = NEXTCLOUD_BASE / LADYS_DIR / PLAYERS_XLSX_NAME
PLAYERS_LOCAL_TMP = Path("tmp") / PLAYERS_XLSX_NAME

MAX_PLAYER_NAME_LEN = 64

DONATIONS_XLSX_NAME = "Donations.xlsx"
DONATIONS_REMOTE_PATH = NEXTCLOUD_BASE / DONATIONS_DIR / DONATIONS_XLSX_NAME
DONATIONS_LOCAL_TMP = Path("tmp") / DONATIONS_XLSX_NAME


def sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "", value.replace(" ", "_"))


def match_sheet_filename(match_id: int, event: str, opponent: str) -> str:
    return f"{match_id}_{sanitize_filename(event)}_{sanitize_filename(opponent)}.xlsx"


def match_sheet_local_path(output_path: Path, season: int, filename: str) -> Path:
    """The local mirror keeps the remote layout, so both can be compared by eye."""
    return output_path / season_subpath(season) / filename


def match_sheet_remote_path_for_filename(season: int, filename: str) -> Path:
    return NEXTCLOUD_BASE / season_subpath(season) / filename


def match_sheet_tmp_path(filename: str) -> Path:
    return Path("tmp") / filename


SHARE_ROOT = "/Scores"


def web_url(subpath: Path | str | None = None) -> str:
    """The share exposes NEXTCLOUD_BASE as /Scores, so remote paths map one to one."""
    path = SHARE_ROOT if subpath is None else f"{SHARE_ROOT}/{Path(subpath).as_posix()}"
    return f"https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path={path}"


def scores_web_url(season: int | None = None) -> str:
    return web_url(None if season is None else season_subpath(season))


def upload_match_sheet(local_path: Path, season: int, filename: str) -> tuple[Optional[str], bool]:
    return upload_file(local_path, match_sheet_remote_path_for_filename(season, filename), overwrite=False)


def download_match_sheet(season: int, filename: str, local_path: Path | None = None) -> Optional[Path]:
    local_path = local_path or match_sheet_tmp_path(filename)
    return download_file(match_sheet_remote_path_for_filename(season, filename), local_path)


def upload_players_workbook(local_path: Path = PLAYERS_LOCAL_TMP) -> tuple[Optional[str], bool]:
    return upload_file(local_path, PLAYERS_REMOTE_PATH, overwrite=True)


def download_players_workbook(local_path: Path = PLAYERS_LOCAL_TMP) -> Optional[Path]:
    return download_file(PLAYERS_REMOTE_PATH, local_path)


def upload_donations_workbook(local_path: Path = DONATIONS_LOCAL_TMP) -> tuple[Optional[str], bool]:
    return upload_file(local_path, DONATIONS_REMOTE_PATH, overwrite=True)


def download_donations_workbook(local_path: Path = DONATIONS_LOCAL_TMP) -> Optional[Path]:
    return download_file(DONATIONS_REMOTE_PATH, local_path)


def delete_local_file(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


def delete_remote_file(remote_path: Path) -> bool:
    return delete_file(remote_path)


def cleanup_imported_workbook(local_path: Path, remote_path: Path) -> str:
    delete_local_file(local_path)
    deleted = delete_remote_file(remote_path)
    return "deleted" if deleted else "delete failed"


def export_players_workbook(
    db_path: str | Path,
    *,
    workbook_builder: WorkbookBuilder,
    workbook_saver: WorkbookSaver,
    excluded_columns: set[str],
    out_path: Path = PLAYERS_LOCAL_TMP,
) -> WorkbookExportOutcome:
    export_data = get_player_export_data(db_path, excluded_columns=excluded_columns)
    if export_data is None:
        return WorkbookExportOutcome(status="TABLE_MISSING")

    workbook = workbook_builder(export_data.columns, export_data.rows)
    workbook_saver(workbook, out_path)

    _, created = upload_players_workbook(out_path)
    delete_local_file(out_path)

    return WorkbookExportOutcome(
        status="EXPORTED",
        label=PLAYERS_REMOTE_PATH.as_posix(),
        web_url=web_url(LADYS_DIR),
        created=created,
    )


def export_donations_workbook(
    db_path: str | Path,
    *,
    workbook_builder: WorkbookBuilder,
    workbook_saver: WorkbookSaver,
    today: str,
    out_path: Path = DONATIONS_LOCAL_TMP,
) -> WorkbookExportOutcome:
    rows = get_donation_export_rows(db_path)
    workbook = workbook_builder(rows, today)
    workbook_saver(workbook, out_path)

    _, created = upload_donations_workbook(out_path)
    delete_local_file(out_path)

    return WorkbookExportOutcome(
        status="EXPORTED",
        label=DONATIONS_REMOTE_PATH.as_posix(),
        web_url=web_url(DONATIONS_DIR),
        created=created,
    )


def export_match_sheet_from_data(
    match: tuple[int, str, int, str, str],
    players: list[tuple[int, str, str | None, str | None]],
    *,
    output_path: Path,
    workbook_builder: WorkbookBuilder,
    workbook_saver: WorkbookSaver,
    absent_checker: AbsentChecker,
) -> WorkbookExportOutcome:
    match_id, _, season, opponent, event = match
    filename = match_sheet_filename(match_id, event, opponent)
    local_path = match_sheet_local_path(output_path, season, filename)

    workbook = workbook_builder(match, players, is_absent_on=absent_checker)
    workbook_saver(workbook, local_path)

    _, created = upload_match_sheet(local_path, season, filename)
    delete_local_file(local_path)

    web_url = scores_web_url(season)
    return WorkbookExportOutcome(
        status="EXPORTED",
        markdown_link=f"[{filename}]({web_url})",
        web_url=web_url,
        created=created,
    )


def export_match_sheet(
    db_path: str | Path,
    match_id: int,
    *,
    output_path: Path,
    workbook_builder: WorkbookBuilder,
    workbook_saver: WorkbookSaver,
    absent_checker: AbsentChecker,
) -> WorkbookExportOutcome:
    export_data = get_match_export_data(db_path, match_id)
    if export_data is None:
        return WorkbookExportOutcome(status="NO_MATCH")
    return export_match_sheet_from_data(
        export_data.match,
        export_data.players,
        output_path=output_path,
        workbook_builder=workbook_builder,
        workbook_saver=workbook_saver,
        absent_checker=absent_checker,
    )


def import_players_workbook(
    db_path: str | Path,
    *,
    workbook_reader: PlayerWorkbookReader,
    excluded_columns: set[str],
    local_xlsx: Optional[Path] = None,
) -> PlayerWorkbookImportOutcome:
    local = local_xlsx or download_players_workbook()
    if not local or not local.exists():
        return PlayerWorkbookImportOutcome(status="NOT_FOUND")

    header, workbook_rows = workbook_reader(local)
    if header is None or workbook_rows is None:
        delete_local_file(local)
        return PlayerWorkbookImportOutcome(status="INVALID_HEADER")

    result = import_player_rows(db_path, workbook_rows, excluded_columns=excluded_columns)
    cleanup_status = cleanup_imported_workbook(local, PLAYERS_REMOTE_PATH)
    return PlayerWorkbookImportOutcome(status="IMPORTED", result=result, cleanup_status=cleanup_status)


def import_donations_workbook(
    db_path: str | Path,
    *,
    workbook_reader: DonationWorkbookReader,
    local_xlsx: Optional[Path] = None,
) -> DonationWorkbookImportOutcome:
    local = local_xlsx or download_donations_workbook()
    if not local or not local.exists():
        return DonationWorkbookImportOutcome(status="NOT_FOUND")

    date_str, donation_entries, errors = workbook_reader(local)
    if date_str is None:
        delete_local_file(local)
        return DonationWorkbookImportOutcome(status="INVALID_DATE")

    result = import_donation_entries(
        db_path,
        date_str,
        donation_entries,
        initial_errors=errors,
    )
    cleanup_status = cleanup_imported_workbook(local, DONATIONS_REMOTE_PATH)
    return DonationWorkbookImportOutcome(status="IMPORTED", result=result, cleanup_status=cleanup_status)


def import_match_sheet(
    db_path: str | Path,
    match_id: int,
    *,
    workbook_reader: MatchSheetWorkbookReader,
) -> MatchSheetImportOutcome:
    export_data = get_match_export_data(db_path, match_id)
    if export_data is None:
        return MatchSheetImportOutcome(status="NO_MATCH")

    match = export_data.match
    match_id, _, season, opponent, event = match
    filename = match_sheet_filename(match_id, event, opponent)
    local_path = match_sheet_tmp_path(filename)

    downloaded = download_match_sheet(season, filename, local_path)
    if not downloaded or not downloaded.exists():
        return MatchSheetImportOutcome(status="NOT_FOUND", filename=filename, web_url=scores_web_url(season))

    ladyscore, oppscore, rows = workbook_reader(downloaded)
    validation = validate_match_sheet_rows(
        lady_score=ladyscore,
        opponent_score=oppscore,
        rows=rows,
    )

    if validation.errors:
        delete_local_file(downloaded)
        return MatchSheetImportOutcome(
            status="VALIDATION_ERRORS",
            filename=filename,
            web_url=scores_web_url(season),
            validation_errors=validation.errors,
        )

    result = apply_match_sheet_entries(
        match_id=match_id,
        entries=validation.entries,
        score_ladys=ladyscore if ladyscore is not None else 0,
        score_opponent=oppscore if oppscore is not None else 0,
        name_updates=validation.name_updates,
    )

    delete_local_file(downloaded)
    return MatchSheetImportOutcome(
        status="IMPORTED",
        filename=filename,
        web_url=scores_web_url(season),
        result=result,
    )


def to_k(value: Optional[int]) -> float:
    try:
        return round((int(value or 0)) / 1000.0, 1)
    except (TypeError, ValueError):
        return 0.0


def parse_k_amount(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return int(value) * 1000
    if isinstance(value, float):
        return int(round(value * 1000))
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            return None
        text = text.replace("k", "").strip()
        text = text.replace(" ", "").replace("_", "")
        text = text.replace(",", ".")
        if not re.fullmatch(r"-?\d+(\.\d+)?", text):
            return None
        parsed = float(text)
        if parsed < 0:
            return None
        return int(round(parsed * 1000))
    return None


def import_player_rows(
    db_path: str | Path,
    workbook_rows: list[dict[str, Any]],
    *,
    excluded_columns: set[str],
) -> PlayerImportResult:
    with db_connection.connect_path(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("PRAGMA table_info(players)")
        db_cols_info = cur.fetchall()
        db_cols = [c[1] for c in db_cols_info]
        db_cols_set = set(db_cols)

        allowed_import_cols = (db_cols_set - excluded_columns) | {"id"}
        bool_cols = _detect_boolean_columns(conn, "players", candidate_overrides={"active", "is_leader"})

        cur.execute("SELECT id FROM players WHERE team='PLTE'")
        existing_ids = {r[0] for r in cur.fetchall()}

        updated = 0
        inserted = 0
        skipped = 0
        errors = 0
        messages: list[str] = []

        for row_map_full in workbook_rows:
            row_map = {k: v for k, v in row_map_full.items() if k in allowed_import_cols}

            if all((v is None or str(v).strip() == "") for v in row_map.values()):
                continue

            rid_int = _read_int(row_map.get("id"))

            for bool_col in set(row_map.keys()) & bool_cols:
                row_map[bool_col] = _to_bool01_if_needed(row_map[bool_col])

            try:
                if rid_int and rid_int in existing_ids:
                    set_cols = [c for c in row_map.keys() if c != "id"]
                    if not set_cols:
                        skipped += 1
                        continue

                    cur.execute(f"SELECT {', '.join(set_cols)} FROM players WHERE id = ?", (rid_int,))
                    db_row = cur.fetchone()
                    if not db_row:
                        skipped += 1
                        continue
                    db_map = {col: db_row[idx] for idx, col in enumerate(set_cols)}

                    changed_cols = [c for c in set_cols if _norm(row_map[c]) != _norm(db_map.get(c))]
                    if not changed_cols:
                        skipped += 1
                        continue

                    now = timestamps.utc_now()
                    placeholders = ", ".join([f"{c}=?" for c in changed_cols] + ["last_modified=?"])
                    values = [row_map[c] for c in changed_cols] + [now, rid_int]
                    cur.execute(f"UPDATE players SET {placeholders} WHERE id = ?", values)
                    updated += 1
                else:
                    row_map["team"] = "PLTE"
                    if "active" not in row_map or row_map["active"] is None:
                        row_map["active"] = 1

                    insert_cols = [
                        c for c in row_map.keys()
                        if c != "id" and (c not in excluded_columns or c == "team")
                    ]
                    if not insert_cols:
                        skipped += 1
                        continue

                    now = timestamps.utc_now()
                    insert_cols.append("last_modified")
                    placeholders = ", ".join(["?"] * len(insert_cols))
                    values = [row_map[c] for c in insert_cols if c != "last_modified"] + [now]
                    cur.execute(
                        f"INSERT INTO players ({', '.join(insert_cols)}) VALUES ({placeholders})",
                        values,
                    )
                    inserted += 1
            except (sqlite3.Error, ValueError, TypeError) as e:
                errors += 1
                messages.append(_import_failure("player", rid_int, e))

        conn.commit()

    return PlayerImportResult(
        updated=updated, inserted=inserted, skipped=skipped, errors=errors, messages=messages
    )


def get_player_export_data(db_path: str | Path, *, excluded_columns: set[str]) -> PlayerExportData | None:
    with db_connection.connect_path(db_path) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(players)")
        cols_info = cur.fetchall()
        if not cols_info:
            return None
        all_columns = [column[1] for column in cols_info]
        export_columns = [column for column in all_columns if column not in excluded_columns]

        cur.execute(f"""
            SELECT {', '.join(export_columns)}
            FROM players
            WHERE team = 'PLTE' AND active = 1
            ORDER BY garage_power DESC, name COLLATE NOCASE
        """)
        return PlayerExportData(columns=export_columns, rows=cur.fetchall())


def get_donation_export_rows(db_path: str | Path) -> list[tuple[int, str, int]]:
    with db_connection.connect_path(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name
            FROM players
            WHERE active = 1 AND team = 'PLTE'
        """)
        players = cur.fetchall()

        latest = _get_latest_donations(conn)
        rows = []
        for player_id, name in players:
            _, total = latest.get(player_id, (None, 0))
            rows.append((player_id, name, int(total or 0)))

    rows.sort(key=lambda row: (-row[2], (row[1] or "").lower()))
    return rows


def get_match_export_data(db_path: str | Path, match_id: int) -> MatchExportData | None:
    with db_connection.connect_path(db_path) as conn:
        match = _get_match_info(conn, match_id)
        if match is None:
            return None

        _, _, season, _, _ = match
        players = _rank_active_plte_for_season(conn, season) or _get_active_players(conn)
        return MatchExportData(match=match, players=players)


def import_donation_entries(
    db_path: str | Path,
    date_str: str,
    donation_entries: list[tuple[int, int]],
    *,
    initial_errors: int = 0,
) -> DonationImportResult:
    added = 0
    errors = initial_errors
    messages: list[str] = []
    if initial_errors:
        messages.append(f"{initial_errors} row(s) skipped while reading the workbook")

    with db_connection.connect_path(db_path) as conn:
        for player_id, total in donation_entries:
            try:
                conn.execute(
                    """
                    INSERT INTO donation (player_id, date, total)
                    VALUES (?, ?, ?)
                    ON CONFLICT(player_id, date) DO UPDATE SET total = excluded.total
                    """,
                    (player_id, date_str, total),
                )
                added += 1
            except (sqlite3.Error, ValueError, TypeError) as e:
                errors += 1
                messages.append(_import_failure("donation for player", player_id, e))

    return DonationImportResult(added=added, errors=errors, messages=messages)


def _import_failure(what: str, key, error: Exception) -> str:
    """One line per failed row - "4 errors" alone is not diagnosable."""
    return f"{what} {key if key is not None else '?'}: {type(error).__name__}: {error}"


def add_plte_player_from_sheet(name: str) -> int | None:
    clean_name = (name or "").strip()
    if not clean_name:
        return None
    result = player_service.add_player(name=clean_name, team="PLTE")
    if result.status != "ADDED":
        return None
    return result.player_id


def validate_match_sheet_rows(
    *,
    lady_score: int | None,
    opponent_score: int | None,
    rows: list[tuple[int, tuple]],
    player_creator=add_plte_player_from_sheet,
) -> MatchSheetValidationResult:
    errors: list[str] = []
    entries: list[dict[str, int]] = []
    name_updates: list[dict[str, Any]] = []

    if lady_score is None or opponent_score is None:
        errors.append("Row 2: please fill team scores in C2 (Power Ladies) and D2 (Opponent).")

    for row_idx, row in rows:
        pid_cell = row[1]
        player_name_cell = row[2]

        mode, pid_or_msg = parse_player_id_marker(pid_cell)
        if mode == "SKIP":
            continue
        if mode == "ERROR":
            errors.append(f"Row {row_idx}: {pid_or_msg}")
            continue
        if mode == "CREATE":
            name = (player_name_cell or "").strip()
            if not name:
                errors.append(f"Row {row_idx}: cannot create player – column C (Player) is empty.")
                continue
            new_id = player_creator(name)
            if not new_id:
                errors.append(f"Row {row_idx}: failed to create player '{name}'.")
                continue
            player_id = int(new_id)
        else:
            player_id = int(pid_or_msg)
            name_update = _match_sheet_name_update(
                player_id=player_id,
                name_cell=player_name_cell,
                row_idx=row_idx,
                errors=errors,
            )
            if name_update is not None:
                name_updates.append(name_update)

        score_cell = row[3] if len(row) >= 4 else None
        points_cell = row[4] if len(row) >= 5 else None
        absent_raw = row[5] if len(row) >= 6 else "false"
        checkin_raw = row[6] if len(row) >= 7 else "false"

        score_val = _strict_int(score_cell, "Score", row_idx, errors)
        points_val = _strict_int(points_cell, "Points", row_idx, errors)

        if score_val is not None and not (0 <= score_val <= 75000):
            errors.append(f"Row {row_idx}: Score out of range (0..75000): {score_val}")
        if points_val is not None and not (0 <= points_val <= 300):
            errors.append(f"Row {row_idx}: Points out of range (0..300): {points_val}")

        if score_val is not None and points_val is not None:
            entries.append({
                "row": row_idx,
                "pid": int(player_id),
                "score": int(score_val),
                "points": int(points_val),
                "absent": int(_to_bool01(absent_raw)),
                "checkin": int(_to_bool01(checkin_raw)),
            })

    errors.extend(_validate_match_sheet_point_order(entries))

    sum_points = sum(entry["points"] for entry in entries)
    if lady_score is not None and sum_points != lady_score:
        errors.append(f"Team points mismatch: sum(points)={sum_points} != C2={lady_score}")

    return MatchSheetValidationResult(entries=entries, errors=errors, name_updates=name_updates)


def apply_match_sheet_entries(
    *,
    match_id: int,
    entries: list[dict[str, int]],
    score_ladys: int,
    score_opponent: int,
    name_updates: list[dict[str, Any]] | tuple = (),
) -> MatchSheetApplyResult:
    renamed, rename_errors = _apply_player_renames(name_updates)

    imported = 0
    changed = 0
    errors = 0

    for entry in entries:
        result = matchscore_service.add_score(
            match_id=match_id,
            player_input=str(entry["pid"]),
            score=int(entry["score"]),
            points=int(entry["points"]),
            absent_override=int(entry["absent"]),
            checkin_override=int(entry["checkin"]),
        )
        if result.status in ("CHANGED", "UNCHANGED"):
            imported += 1
            if result.status == "CHANGED":
                changed += 1
        else:
            errors += 1

    score_updated = match_repo.update_match(
        match_id,
        {"score_ladys": score_ladys, "score_opponent": score_opponent},
    ) > 0

    return MatchSheetApplyResult(
        imported=imported,
        changed=changed,
        score_updated=score_updated,
        errors=errors,
        renamed=renamed,
        rename_errors=rename_errors,
    )


def _match_sheet_name_update(
    *,
    player_id: int,
    name_cell,
    row_idx: int,
    errors: list[str],
) -> dict[str, Any] | None:
    """Column C is a rename candidate; an empty cell never clears the stored name."""
    name = ("" if name_cell is None else str(name_cell)).strip()
    if not name:
        return None
    if len(name) > MAX_PLAYER_NAME_LEN:
        errors.append(
            f"Row {row_idx}: Player name too long (max {MAX_PLAYER_NAME_LEN} characters): '{name}'"
        )
        return None
    return {"row": row_idx, "pid": player_id, "name": name}


def _apply_player_renames(
    name_updates: list[dict[str, Any]] | tuple,
) -> tuple[list[tuple[int, str, str]], list[str]]:
    renamed: list[tuple[int, str, str]] = []
    errors: list[str] = []

    for update in name_updates:
        player_id = int(update["pid"])
        new_name = str(update["name"]).strip()
        current = player_repo.get_player_brief(player_id)
        if current is None:
            # Unknown ID; add_score reports it while importing the score itself.
            continue
        if not new_name or new_name == (current.name or "").strip():
            continue

        result = player_service.edit_player(player_id, name=new_name)
        if result.status == "UPDATED":
            renamed.append((player_id, current.name, new_name))
        else:
            # Wording avoids "invalid"/"not found" — bot.py would colour the whole import as an error.
            errors.append(
                f"Row {update.get('row', '?')}: kept stored name for player {player_id} "
                f"(rename rejected: {result.status})"
            )

    return renamed, errors


def parse_player_id_marker(pid_cell):
    if pid_cell is None:
        return ("SKIP", None)
    if isinstance(pid_cell, float) and float(pid_cell).is_integer():
        return ("OK", int(pid_cell))
    if isinstance(pid_cell, int):
        return ("OK", int(pid_cell))
    text = str(pid_cell).strip().lower()
    if text == "":
        return ("SKIP", None)
    if text in ("a", "add", "new", "+", "none", "-"):
        return ("CREATE", None)
    if text.isdigit():
        return ("OK", int(text))
    return ("ERROR", f"invalid playerID '{pid_cell}' – use a number or 'a'")


def _detect_boolean_columns(conn: sqlite3.Connection, table: str, candidate_overrides=None) -> set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    out = set()
    for _, name, ctype, *_ in cur.fetchall():
        column_type = (ctype or "").upper()
        if "BOOL" in column_type:
            out.add(name)
    if candidate_overrides:
        out |= set(candidate_overrides)
    return out


def _get_latest_donations(conn: sqlite3.Connection) -> dict[int, tuple[str, int]]:
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
    return {player_id: (date, total) for player_id, date, total in cur.fetchall()}


def _get_match_info(conn: sqlite3.Connection, match_id: int) -> tuple[int, str, int, str, str] | None:
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.start, m.season_number, m.opponent, e.name
        FROM match m
        JOIN teamevent e ON m.teamevent_id = e.id
        WHERE m.id = ?
    """, (match_id,))
    return cur.fetchone()


def _get_active_players(conn: sqlite3.Connection) -> list[tuple[int, str, str | None, str | None]]:
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, away_from, away_until
        FROM players
        WHERE active = 1 AND team = 'PLTE'
        ORDER BY name
    """)
    return cur.fetchall()


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


def _rank_active_plte_for_season(conn: sqlite3.Connection, season_number: int) -> list[tuple[int, str, str | None, str | None]]:
    import statistics

    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, away_from, away_until
        FROM players
        WHERE active = 1 AND team = 'PLTE'
    """)
    base_players = cur.fetchall()
    if not base_players:
        return []
    id_to_player = {
        player_id: (player_id, name, away_from, away_until)
        for player_id, name, away_from, away_until in base_players
    }

    rows = _fetch_season_rows(conn, season_number)

    scores_by_match = {}
    for player_id, _name, team, active, score, match_id, tracks in rows:
        if team != "PLTE" or not active:
            continue
        if score is None:
            continue
        scaled = score * 4 / tracks if tracks else score
        scores_by_match.setdefault(match_id, []).append((player_id, scaled))

    player_deltas, player_counts = {}, {}
    for _, entries in scores_by_match.items():
        values = [score for _, score in entries]
        if not values:
            continue
        try:
            median = statistics.median(values)
        except statistics.StatisticsError:
            continue
        for player_id, score in entries:
            delta = score - median
            player_deltas.setdefault(player_id, []).append(delta)
            player_counts[player_id] = player_counts.get(player_id, 0) + 1

    with_scores, without_scores = [], []
    for player_id, (player_id_, name, away_from, away_until) in id_to_player.items():
        deltas = player_deltas.get(player_id)
        if deltas:
            avg_delta = round(sum(deltas) / len(deltas))
            count = player_counts.get(player_id, 0)
            with_scores.append((avg_delta, -count, name.lower(), (player_id_, name, away_from, away_until)))
        else:
            without_scores.append((name.lower(), (player_id_, name, away_from, away_until)))

    with_scores_sorted = [
        player for _, _, _, player in sorted(with_scores, key=lambda item: (item[0], item[1], item[2]), reverse=True)
    ]
    without_scores_sorted = [player for _, player in sorted(without_scores, key=lambda item: item[0])]
    return with_scores_sorted + without_scores_sorted


def _to_bool01_if_needed(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "j\u0061"):
        return 1
    if text in ("0", "false", "no", "n", "n\u0065in", ""):
        return 0
    if isinstance(value, (int, float)):
        return 1 if int(value) != 0 else 0
    return None


def _norm(value):
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        return text if text != "" else None
    return value


def _read_int(value) -> int | None:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _strict_int(value, label: str, row_idx: int, errors: list[str]) -> int | None:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        errors.append(f"Row {row_idx}: {label} must not be empty.")
        return None
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        errors.append(f"Row {row_idx}: {label} must be an integer, got float={value}.")
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
        errors.append(f"Row {row_idx}: {label} must be a number, got '{value}'.")
        return None
    errors.append(f"Row {row_idx}: {label} has invalid type {type(value).__name__}.")
    return None


def _to_bool01(value) -> int:
    if value is None:
        return 0
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "j\u0061"):
        return 1
    if text in ("0", "false", "no", "n", "n\u0065in", ""):
        return 0
    return 0


def _validate_match_sheet_point_order(entries: list[dict[str, int]]) -> list[str]:
    errors: list[str] = []

    seen_high: dict[int, list[dict[str, int]]] = {}
    for entry in entries:
        points = entry["points"]
        if points > 20:
            seen_high.setdefault(points, []).append(entry)
    for points, duplicate_rows in seen_high.items():
        if len(duplicate_rows) > 1:
            ids = ", ".join(f"row {row['row']} (pid {row['pid']})" for row in duplicate_rows)
            errors.append(f"High points duplicated (>20): {points} appears in {ids}")

    entries_sorted = sorted(entries, key=lambda row: (-row["score"], row["pid"]))
    for idx in range(len(entries_sorted) - 1):
        current = entries_sorted[idx]
        next_entry = entries_sorted[idx + 1]
        if current["points"] < next_entry["points"]:
            errors.append(
                f"Monotony violation: row {current['row']} (score {current['score']}, points {current['points']}) "
                f"vs row {next_entry['row']} (score {next_entry['score']}, points {next_entry['points']})"
            )
        if current["points"] == next_entry["points"] and current["points"] >= 20:
            errors.append(
                f"Equal high points not allowed (>=20): rows {current['row']} & {next_entry['row']} "
                f"both {current['points']}"
            )

    return errors
