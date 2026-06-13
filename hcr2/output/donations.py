from __future__ import annotations

from hcr2.models.donation import DonationDateEntry, DonationDateSummary, DonationIndexRow, DonationStats
from modules.common import print_table_header


def format_k(value):
    try:
        val = float(value)
        return f"{val/1000:.1f}K"
    except Exception:
        return str(value)


def print_player_donations(player_id: int, player_name: str, stats: DonationStats) -> None:
    print(f"\n📌 Donations for {player_name} (ID {player_id}):")
    print_table_header(columns=[f"{'ID':4}", f"{'Date':12}", f"{'Total':>8}", f"{'Delta':>8}"], width=36)

    last_ten = stats.entries[-10:]
    for donation_id, ds, total, delta in reversed(last_ten):
        id_str = str(donation_id) if donation_id is not None else "-"
        print(f"{id_str:4} {ds:12} {format_k(total):>8} {format_k(delta):>8}")

    print("\n📊 Stats:")
    print(f"  Average monthly increment: {format_k(stats.avg_monthly_increment)}")


def print_all_stats(rows: list[tuple[int, str, DonationStats]]) -> None:
    print("\n📊 Donations (K):")
    print_table_header(columns=[f"{'ID':4}", f"{'Name':12}", f"{'Tot':>6}", f"{'Inc':>6}", f"{'Avg':>6}"], width=40)

    for player_id, name, stats in rows:
        last_inc = stats.entries[-1][3] if stats.entries else 0
        short_name = name[:12]
        print(
            f"{player_id:4} {short_name:12} {format_k(stats.last_total):>6} "
            f"{format_k(last_inc):>6} {format_k(stats.avg_monthly_increment):>6}"
        )


def print_donation_index(cutoff_date: str, rows: list[DonationIndexRow], *, under_only: bool = False) -> None:
    if under_only:
        print(f"\n📊 Donation index < 100 from 2025-11-01 to {cutoff_date}:")
    else:
        print(f"\n📊 Donation index from 2025-11-01 to {cutoff_date}:")
    print_table_header(columns=[f"{'#':3}", f"{'ID':4}", f"{'Name':12}", f"{'Mch':>4}", f"{'Don':>8}", f"{'Idx':>5}"], width=50)

    for idx, row in enumerate(rows, start=1):
        print(
            f"{idx:3d} {row.player_id:4} {row.player_name[:12]:12} {row.matches:4d} "
            f"{format_k(row.total):>8} {row.index:5.1f}"
        )


def print_donation_dates(rows: list[DonationDateSummary]) -> None:
    print("\n📅 Donation dates:")
    print_table_header(columns=[f"{'Date':12}", f"{'Count':>5}"], width=20)
    for row in rows:
        print(f"{row.date:12} {row.count:5d}")


def print_donations_for_date(date: str, rows: list[DonationDateEntry]) -> None:
    print(f"\n📋 Donations for {date}:")
    print_table_header(columns=[f"{'ID':4}", f"{'PID':4}", f"{'Name':12}", f"{'Team':4}", f"{'Total':>8}"], width=40)

    for row in rows:
        short_name = (row.player_name or "")[:12]
        team_str = (row.team or "")[:4]
        print(f"{row.id:4d} {row.player_id:4d} {short_name:12} {team_str:4} {format_k(row.total):>8}")
