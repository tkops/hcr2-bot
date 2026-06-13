from __future__ import annotations

from datetime import datetime

from hcr2.models.donation import DonationEntry, DonationIndexRow, DonationStats


STATS_START_DATE = "2025-11-01"


def parse_date(ds: str) -> datetime:
    try:
        return datetime.fromisoformat(ds)
    except ValueError:
        return datetime.strptime(ds, "%Y-%m-%d")


def validate_total(total: str | int) -> int:
    total_int = int(total)
    if total_int < 0:
        raise ValueError("total must be >= 0")
    return total_int


def calculate_stats(snapshots: list[DonationEntry]) -> DonationStats:
    if not snapshots:
        return DonationStats(entries=[], last_total=0, total_donated=0, avg_monthly_increment=0.0)

    parsed = []
    for snapshot in snapshots:
        dt = parse_date(snapshot.date)
        parsed.append((dt, snapshot.id, snapshot.date, int(snapshot.total)))

    if not parsed:
        return DonationStats(entries=[], last_total=0, total_donated=0, avg_monthly_increment=0.0)

    parsed.sort(key=lambda x: x[0])

    entries = []
    total_donated = 0
    prev_total = None

    for _dt, donation_id, ds, total in parsed:
        delta = 0 if prev_total is None else (total - prev_total)
        entries.append((donation_id, ds, total, delta))
        if prev_total is not None:
            total_donated += delta
        prev_total = total

    last_total = parsed[-1][3]

    month_last = {}
    for dt, _donation_id, _ds, total in parsed:
        key = f"{dt.year:04d}-{dt.month:02d}"
        if key not in month_last or dt > month_last[key][0]:
            month_last[key] = (dt, total)

    month_points = sorted(month_last.items(), key=lambda kv: kv[1][0])
    month_deltas = []
    for i in range(1, len(month_points)):
        month_deltas.append(month_points[i][1][1] - month_points[i - 1][1][1])
    avg_monthly = sum(month_deltas) / len(month_deltas) if month_deltas else 0.0

    return DonationStats(
        entries=entries,
        last_total=last_total,
        total_donated=total_donated,
        avg_monthly_increment=avg_monthly,
    )


def build_index_row(player_id: int, name: str, matches: int, total: int) -> DonationIndexRow:
    expected = matches * 600
    index = (total / expected) * 100 if expected > 0 else 0.0
    return DonationIndexRow(player_id=player_id, player_name=name, matches=matches, total=total, index=index)
