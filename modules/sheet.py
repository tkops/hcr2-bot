#!/usr/bin/env python3
from typing import Optional
from pathlib import Path
from datetime import date
from hcr2.exporters import excel as excel_exporter
from hcr2.output import sheets as sheet_output
from hcr2.services import sheets as sheet_service
from modules.common import (
    DB_PATH,
    is_absent_on,
    is_help_request,
    parse_date_or_none,
    parse_int,
    print_command_help,
    print_unknown_command,
)

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

PLAYERS_LOCAL_TMP = sheet_service.PLAYERS_LOCAL_TMP

DONATIONS_LOCAL_TMP = sheet_service.DONATIONS_LOCAL_TMP


def sanitize_filename(s):
    return sheet_service.sanitize_filename(s)


def _is_absent_on(match_day: date, frm: Optional[str], until: Optional[str]) -> bool:
    return is_absent_on(match_day, frm, until)


def _is_absent_on_match_day(match_day_str: str, frm: Optional[str], until: Optional[str]) -> bool:
    match_day = parse_date_or_none(match_day_str) or date(1970, 1, 1)
    return _is_absent_on(match_day, frm, until)


# -------------------- Excel Generation & Import (Match Sheet) --------------------

def generate_excel(match, players, output_path):
    """
    Match sheet. Unchanged except for standard formatting.
    """
    outcome = sheet_service.export_match_sheet_from_data(
        match,
        players,
        output_path=output_path,
        workbook_builder=excel_exporter.build_match_sheet_workbook,
        workbook_saver=excel_exporter.save_workbook,
        absent_checker=_is_absent_on_match_day,
    )
    return outcome.markdown_link, outcome.created


def import_excel_to_matchscore(match_id):
    outcome = sheet_service.import_match_sheet(
        DB_PATH,
        match_id,
        workbook_reader=excel_exporter.read_match_sheet_workbook,
    )
    if outcome.status == "NO_MATCH":
        sheet_output.print_no_match_found()
        return
    if outcome.status == "NOT_FOUND":
        sheet_output.print_match_excel_not_found()
        return
    if outcome.status == "VALIDATION_ERRORS":
        sheet_output.print_validation_errors(outcome.validation_errors or [])
        return

    sheet_output.print_match_import_result(outcome.filename or "", outcome.web_url or "", outcome.result)


# ===================== Players: Export/Import (active PLTE, excludes, formatting) =====================

def export_players_to_excel(db_path: str = DB_PATH, out_path: Path = PLAYERS_LOCAL_TMP):
    outcome = sheet_service.export_players_workbook(
        db_path,
        workbook_builder=excel_exporter.build_players_workbook,
        workbook_saver=excel_exporter.save_workbook,
        excluded_columns=EXCLUDED_PLAYER_COLS,
        out_path=out_path,
    )
    if outcome.status == "TABLE_MISSING":
        sheet_output.print_players_table_not_found()
        return

    sheet_output.print_exported_workbook(outcome.label or "", outcome.web_url or "", outcome.created)


def import_players_from_excel(db_path: str = DB_PATH, local_xlsx: Optional[Path] = None):
    outcome = sheet_service.import_players_workbook(
        db_path,
        workbook_reader=excel_exporter.read_players_workbook,
        excluded_columns=EXCLUDED_PLAYER_COLS,
        local_xlsx=local_xlsx,
    )
    if outcome.status == "NOT_FOUND":
        sheet_output.print_players_excel_not_found()
        return
    if outcome.status == "INVALID_HEADER":
        sheet_output.print_invalid_players_header()
        return

    sheet_output.print_player_import_result(outcome.result, outcome.cleanup_status or "delete failed")


# ===================== Donations: Export/Import =====================

def export_donations_to_excel(db_path: str = DB_PATH, out_path: Path = DONATIONS_LOCAL_TMP):
    outcome = sheet_service.export_donations_workbook(
        db_path,
        workbook_builder=excel_exporter.build_donations_workbook,
        workbook_saver=excel_exporter.save_workbook,
        today=date.today().isoformat(),
        out_path=out_path,
    )
    sheet_output.print_exported_workbook(outcome.label or "", outcome.web_url or "", outcome.created)

def import_donations_from_excel(db_path: str = DB_PATH, local_xlsx: Optional[Path] = None):
    outcome = sheet_service.import_donations_workbook(
        db_path,
        workbook_reader=excel_exporter.read_donations_workbook,
        local_xlsx=local_xlsx,
    )
    if outcome.status == "NOT_FOUND":
        sheet_output.print_donations_excel_not_found()
        return
    if outcome.status == "INVALID_DATE":
        sheet_output.print_invalid_donations_date()
        return

    sheet_output.print_donation_import_result(outcome.result, outcome.cleanup_status or "delete failed")


# ===================== CLI =====================

USAGE_SHEET_CREATE = "Usage: sheet create <match_id>"
USAGE_SHEET_IMPORT = "Usage: sheet import <match_id>"
USAGE_SHEET_PLAYER = "Usage: sheet player <export|import>"
USAGE_SHEET_DONATIONS = "Usage: sheet donations <export|import>"

def print_help():
    print_command_help(
        usage="hcr2.py sheet <command> [options]",
        commands=[
            ("create <match_id>", "Create one Excel file and upload it to Nextcloud"),
            ("import <match_id>", "Import scores from one Excel file on Nextcloud"),
            ("player export", "Export active PLTE players to Ladys.xlsx"),
            ("player import", "Import active PLTE players from Ladys.xlsx"),
            ("donations export", "Export donations sheet for active PLTE players"),
            ("donations import", "Import donations from Donations.xlsx"),
        ],
    )


def handle_command(command, args):
    if is_help_request(command, *args):
        print_help()
        return

    handlers = {
        "create": _handle_create,
        "import": _handle_import,
        "player": _handle_player,
        "donations": _handle_donations,
    }
    handler = handlers.get(command)
    if handler is None:
        print_unknown_command("sheet", command)
        print_help()
        return
    handler(args)


def _parse_match_id_arg(args, usage: str):
    if len(args) != 1:
        print(usage)
        return None
    match_id = parse_int(args[0], default=None)
    if match_id is None:
        sheet_output.print_invalid_match_id()
        return None
    return match_id


def _handle_create(args):
    match_id = _parse_match_id_arg(args, USAGE_SHEET_CREATE)
    if match_id is None:
        return

    outcome = sheet_service.export_match_sheet(
        DB_PATH,
        match_id,
        output_path=sheet_service.NEXTCLOUD_BASE,
        workbook_builder=excel_exporter.build_match_sheet_workbook,
        workbook_saver=excel_exporter.save_workbook,
        absent_checker=_is_absent_on_match_day,
    )
    if outcome.status == "NO_MATCH":
        sheet_output.print_no_match_found()
        return

    sheet_output.print_match_sheet_link_created(outcome.markdown_link or "", outcome.created)


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
