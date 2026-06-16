from __future__ import annotations

from hcr2.services.sheets import DonationImportResult, MatchSheetApplyResult, PlayerImportResult


def print_exported_workbook(label: str, web_url: str, created: bool) -> None:
    print(f"✅ [{label}]({web_url}) ({'Created' if created else 'Updated'})")


def print_match_sheet_link_created(markdown_link: str, created: bool) -> None:
    print(f"✅ {markdown_link} ({'Created' if created else 'Already existed'})")


def print_match_import_result(filename: str, web_url: str, result: MatchSheetApplyResult) -> None:
    status = "Changed" if result.changed > 0 else "Unchanged"
    score_status = "Score updated" if result.score_updated else "Score update failed"
    print(
        f"✅ [{filename}]({web_url}) "
        f"({status}, {result.imported} imported, {result.changed} changed; {score_status})"
    )


def print_validation_errors(errors: list[str]) -> None:
    print("❌ Import aborted due to validation errors:")
    for msg in errors:
        print(" -", msg)


def print_no_match_found() -> None:
    print("❌ No match found.")


def print_match_excel_not_found() -> None:
    print("❌ match Excel not found on Nextcloud")


def print_players_table_not_found() -> None:
    print("❌ players table not found")


def print_players_excel_not_found() -> None:
    print("❌ players Excel not found on Nextcloud")


def print_invalid_players_header() -> None:
    print("❌ First row must contain column names including 'id'")


def print_donations_excel_not_found() -> None:
    print("❌ donations Excel not found on Nextcloud")


def print_invalid_donations_date() -> None:
    print("❌ No valid date in cell A2")


def print_invalid_match_id() -> None:
    print("❌ Match ID must be an integer.")


def print_player_import_result(result: PlayerImportResult, cleanup_status: str) -> None:
    print(
        f"✅ players import: {result.updated} updated, {result.inserted} inserted, "
        f"{result.skipped} skipped, {result.errors} errors ({cleanup_status} in Nextcloud)"
    )


def print_donation_import_result(result: DonationImportResult, cleanup_status: str) -> None:
    print(f"✅ donations import: {result.added} added, {result.errors} errors ({cleanup_status} in Nextcloud)")
