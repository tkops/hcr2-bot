from typing import Callable

from hcr2.models.donation import DonationEntry
from hcr2.output import donations as donation_output
from hcr2.repositories import donations as donation_repo
from hcr2.services import donations as donation_service
from modules.common import (
    get_arg_value,
    is_help_request,
    print_command_help,
    print_unknown_command,
)

# Fixed start date for match counting.
STATS_START_DATE = "2025-11-01"


USAGE_ADD = "Usage: donations add <player_id> <date> <total> | --player <player_id> --date <date> --total <total>"
USAGE_DELETE = "Usage: donations delete <donation_id> | --id <donation_id>"
USAGE_EDIT = "Usage: donations edit <donation_id> <total> | --id <donation_id> <total>"
USAGE_SHOW = "Usage: donations show [<player_id>] | [--player <player_id>]"
USAGE_LIST = "Usage: donations list [<date>] | [--date <date>]"


def print_help():
    print_command_help(
        usage="hcr2.py donations <command> [options]",
        commands=[
            ("add --player <player_id> --date <date> --total <total>", "Add one donation snapshot (cumulative total)"),
            ("delete --id <donation_id>", "Delete one donation entry"),
            ("edit --id <donation_id> <total>", "Edit one donation total"),
            ("show [--player <player_id>]", "Show one player's donations, or stats for all active players"),
            ("stats", "Show donation index per active player"),
            ("under", "Show players with donation index below 100"),
            ("list [--date <date>]", "List donation dates or entries for one date"),
        ],
        notes=["Legacy positional aliases are still accepted for add, delete, edit, show and list."],
    )


def handle_command(command, args):
    if is_help_request(command, *args):
        print_help()
        return

    handlers: dict[str, Callable[[list[str]], None]] = {
        "add": _handle_add,
        "delete": _handle_delete,
        "edit": _handle_edit,
        "show": _handle_show,
        "stats": _handle_stats,
        "under": _handle_under,
        "list": _handle_list,
    }
    handler = handlers.get(command)
    if handler is None:
        print_unknown_command("donations", command)
        print_help()
        return
    handler(args)


def _handle_add(args):
    player_id = get_arg_value(args, "--player")
    date = get_arg_value(args, "--date")
    total = get_arg_value(args, "--total")
    if player_id is not None or date is not None or total is not None:
        if player_id is None or date is None or total is None:
            print(USAGE_ADD)
            return
        add_donation(player_id, date, total)
        return
    if len(args) != 3:
        print(USAGE_ADD)
        return
    add_donation(args[0], args[1], args[2])


def _handle_delete(args):
    donation_id = _extract_donation_id(args)
    if donation_id is None:
        print(USAGE_DELETE)
        return
    delete_donation(donation_id)


def _handle_edit(args):
    donation_id = _extract_donation_id(args)
    if donation_id is None:
        print(USAGE_EDIT)
        return
    total = args[2] if args and args[0] == "--id" and len(args) > 2 else (args[1] if len(args) > 1 else None)
    if total is None:
        print(USAGE_EDIT)
        return
    edit_donation(donation_id, total)


def _handle_show(args):
    player_id = get_arg_value(args, "--player")
    if player_id is not None:
        show_player_donations(player_id)
    elif len(args) == 0:
        show_all_stats()
    elif len(args) == 1:
        show_player_donations(args[0])
    else:
        print(USAGE_SHOW)


def _handle_stats(args):
    if args:
        print("Usage: donations stats")
        return
    show_donation_index()


def _handle_under(args):
    if args:
        print("Usage: donations under")
        return
    show_donation_index_under()


def _handle_list(args):
    date_arg = get_arg_value(args, "--date")
    if date_arg is not None:
        list_donations_for_date(date_arg)
    elif len(args) == 0:
        list_donation_dates()
    elif len(args) == 1:
        list_donations_for_date(args[0])
    else:
        print(USAGE_LIST)


def _extract_donation_id(args):
    if not args:
        return None
    if args[0] == "--id":
        return args[1] if len(args) > 1 else None
    return args[0] if len(args) == 1 or len(args) == 2 else None


# ---------------- Core Functions ---------------- #


def add_donation(player_id, date, total):
    try:
        total_int = donation_service.validate_total(total)
        _ = donation_service.parse_date(date)
        donation_repo.upsert_donation(int(player_id), date, total_int)
        print(
            f"✅ Donation snapshot added for player {player_id} on {date} (total: {total_int})"
        )
    except ValueError as e:
        if str(e) == "total must be >= 0":
            print("❌ total must be >= 0")
        else:
            print(f"❌ Error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


def delete_donation(donation_id):
    try:
        rowcount = donation_repo.delete_donation(int(donation_id))
        if rowcount == 0:
            print(f"ℹ️ No donation with id {donation_id} found.")
        else:
            print(f"✅ Donation {donation_id} deleted")
    except Exception as e:
        print(f"❌ Error: {e}")


def edit_donation(donation_id, new_total):
    """
    Edit only the 'total' field of a single donation entry.
    """
    try:
        total_int = donation_service.validate_total(new_total)
        row = donation_repo.get_donation(int(donation_id))
        if not row:
            print(f"ℹ️ No donation with id {donation_id} found.")
            return

        player_id, date, old_total = row
        donation_repo.update_total(int(donation_id), total_int)

        print(
            f"✅ Donation {donation_id} updated for player {player_id} on {date}: "
            f"{old_total} -> {total_int}"
        )

    except ValueError as e:
        if str(e) == "total must be >= 0":
            print("❌ total must be >= 0")
        else:
            print("❌ total must be an integer")
    except Exception as e:
        print(f"❌ Error: {e}")


# ---------------- Show for One Player ---------------- #


def show_player_donations(player_id):
    try:
        pid = int(player_id)
        player_name = donation_repo.get_player_name(pid)
        if not player_name:
            print("❌ Player not found.")
            return

        snapshots = donation_repo.list_player_donations(pid)
        if not snapshots:
            print(f"ℹ️ No donations found for {player_name}.")
            return

        stats = donation_service.calculate_stats(snapshots)
        donation_output.print_player_donations(pid, player_name, stats)

    except Exception as e:
        print(f"❌ Error: {e}")


# ---------------- Show All Players (Donation-Only-Stats) ---------------- #


def show_all_stats():
    try:
        players = donation_repo.list_active_players()
        if not players:
            print("ℹ️ No active players.")
            return

        rows = []
        for pid, name in players:
            stats = donation_service.calculate_stats(donation_repo.list_player_totals(pid))
            rows.append((pid, name, stats))
        donation_output.print_all_stats(rows)

    except Exception as e:
        print(f"❌ Error: {e}")


# -------- Shared calculation for donation index -------- #


def _compute_donation_index_results():
    """
    Returns (cutoff_date, results)

    results is a list of DonationIndexRow values
    for all active PLTE players.
    """
    cutoff_date = donation_repo.get_latest_donation_date()
    if cutoff_date is None:
        return None, []

    players = donation_repo.list_active_plte_players()
    if not players:
        return cutoff_date, []

    results = []
    for pid, name in players:
        matches = donation_repo.count_player_matches_between(pid, STATS_START_DATE, cutoff_date)
        total = donation_repo.get_player_latest_total(pid, cutoff_date)
        results.append(donation_service.build_index_row(pid, name, matches, total))

    return cutoff_date, results


# ---------------- New Stats / Index (all) ---------------- #


def show_donation_index():
    """
    List all active PLTE players with:
      - running number
      - ID
      - matches since STATS_START_DATE
      - donation total
      - index = (donation_total / (matches * 600)) * 100
    Sorted by index DESCENDING (lowest at bottom)
    """
    cutoff_date, results = _compute_donation_index_results()

    if cutoff_date is None:
        print("ℹ️ No donations found in database.")
        return

    if not results:
        print("ℹ️ No active players in team PLTE.")
        return

    # Sort by descending index, with lower values at the bottom.
    results.sort(key=lambda row: row.index, reverse=True)
    donation_output.print_donation_index(cutoff_date, results)


# ---------------- New Stats / Index (under 100) ---------------- #


def show_donation_index_under():
    """
    Same as show_donation_index(), but only players with index < 100.
    Intended for Discord bot usage.
    """
    cutoff_date, results = _compute_donation_index_results()

    if cutoff_date is None:
        print("ℹ️ No donations found in database.")
        return

    # Filter: index < 100 only.
    results = [row for row in results if row.index < 100.0]

    if not results:
        print("ℹ️ No players with donation index below 100 in team PLTE.")
        return

    # Sort by ascending index, worst first.
    results.sort(key=lambda row: row.index)
    donation_output.print_donation_index(cutoff_date, results, under_only=True)


# ---------------- List dates / entries ---------------- #


def list_donation_dates():
    """
    Show unique donation dates with count of entries, like a sort -u on dates.
    """
    try:
        rows = donation_repo.list_donation_dates()

        if not rows:
            print("ℹ️ No donations found.")
            return

        donation_output.print_donation_dates(rows)

    except Exception as e:
        print(f"❌ Error: {e}")


def list_donations_for_date(date_str: str):
    """
    Show all donation entries for a given date.
    """
    # Validate date format, but use the original string for the query.
    try:
        _ = donation_service.parse_date(date_str)
    except Exception:
        print("❌ Invalid date format. Use YYYY-MM-DD or ISO 8601.")
        return

    try:
        rows = donation_repo.list_donations_for_date(date_str)

        if not rows:
            print(f"ℹ️ No donations found for date {date_str}.")
            return

        donation_output.print_donations_for_date(date_str, rows)

    except Exception as e:
        print(f"❌ Error: {e}")


# ---------------- Helper ---------------- #


def calculate_stats(snapshots):
    """
    snapshots can be:
      - [(date, total), ...]
      - [(id, date, total), ...]
    Returns:
      {
        "entries": [(donation_id, ds, tot, delta), ...],
        "last_total": int,
        "total_donated": int,
        "avg_monthly_increment": float,
      }
    """
    entries = []
    for row in snapshots:
        if len(row) == 3:
            donation_id, ds, total = row
        elif len(row) == 2:
            donation_id = None
            ds, total = row
        else:
            continue
        entries.append(DonationEntry(id=donation_id, date=ds, total=int(total)))
    stats = donation_service.calculate_stats(entries)

    return {
        "entries": stats.entries,
        "last_total": stats.last_total,
        "total_donated": stats.total_donated,
        "avg_monthly_increment": stats.avg_monthly_increment,
    }


def _parse_date(ds: str):
    return donation_service.parse_date(ds)


def format_k(value):
    return donation_output.format_k(value)
