from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

from hcr2.integrations.nextcloud import NEXTCLOUD_BASE
from hcr2.repositories import matches as match_repo
from hcr2.services import matchscores as matchscore_service
from hcr2.services import players as player_service


@dataclass(frozen=True)
class PlayerImportResult:
    updated: int
    inserted: int
    skipped: int
    errors: int


@dataclass(frozen=True)
class DonationImportResult:
    added: int
    errors: int


@dataclass(frozen=True)
class MatchSheetApplyResult:
    imported: int
    changed: int
    score_updated: bool
    errors: int = 0


def sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "", value.replace(" ", "_"))


def match_sheet_filename(match_id: int, event: str, opponent: str) -> str:
    return f"{match_id}_{sanitize_filename(event)}_{sanitize_filename(opponent)}.xlsx"


def match_sheet_local_path(output_path: Path, season: int, filename: str) -> Path:
    return output_path / f"S{season}" / filename


def match_sheet_remote_path_for_filename(season: int, filename: str) -> Path:
    return NEXTCLOUD_BASE / f"S{season}" / filename


def scores_web_url(season: int | None = None) -> str:
    path = "/Scores" if season is None else f"/Scores/S{season}"
    return f"https://t4s.srvdns.de/s/MCneXpH3RPB6XKs?path={path}"


def to_k(value: Optional[int]) -> float:
    try:
        return round((int(value or 0)) / 1000.0, 1)
    except Exception:
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
    with sqlite3.connect(db_path) as conn:
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

                    now = datetime.now().isoformat(timespec="seconds")
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

    return PlayerImportResult(updated=updated, inserted=inserted, skipped=skipped, errors=errors)


def import_donation_entries(
    db_path: str | Path,
    date_str: str,
    donation_entries: list[tuple[int, int]],
    *,
    initial_errors: int = 0,
) -> DonationImportResult:
    added = 0
    errors = initial_errors

    with sqlite3.connect(db_path) as conn:
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
            except Exception:
                errors += 1

    return DonationImportResult(added=added, errors=errors)


def add_plte_player_from_sheet(name: str) -> int | None:
    clean_name = (name or "").strip()
    if not clean_name:
        return None
    result = player_service.add_player(name=clean_name, team="PLTE")
    if result.status != "ADDED":
        return None
    return result.player_id


def apply_match_sheet_entries(
    *,
    match_id: int,
    entries: list[dict[str, int]],
    score_ladys: int,
    score_opponent: int,
) -> MatchSheetApplyResult:
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
    )


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
