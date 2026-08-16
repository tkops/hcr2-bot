from __future__ import annotations

from collections.abc import Sequence

from hcr2.models.distance import DistanceHistoryRow, DistanceRankRow, DistanceWeek
from hcr2.output.tables import print_table
from hcr2.services.distances import AddDistanceResult, ImportResult


def print_no_data(year: int, week: int) -> None:
    print(f"⚠️ No kilometres stored for {year} W{week:02d}.")


def print_invalid_week() -> None:
    print("❌ Invalid year/week - give both or neither.")


def print_ranking(year: int, week: int, rows: Sequence[DistanceRankRow]) -> None:
    if not rows:
        print_no_data(year, week)
        return

    total = sum(row.km for row in rows)
    print(f"🚗 Kilometres {year} W{week:02d} – {len(rows)} players, {total} km")
    # A full roster has to stay inside one Discord message, so the columns are only
    # as wide as the data actually needs.
    print_table(
        headers=[f"{'#':>2}", f"{'Player':<14}", f"{'km':>5}", f"{'avg':>5}", "+-"],
        rows=[
            [
                f"{index:>2}",
                f"{_short(row.name):<14}",
                f"{row.km:>5}",
                f"{row.average:>5.0f}",
                _trend(row.km, row.average),
            ]
            for index, row in enumerate(rows, start=1)
        ],
        width=38,
    )


def _short(name: str, width: int = 14) -> str:
    return name if len(name) <= width else name[: width - 1] + "…"


def _trend(km: int, average: float) -> str:
    if average <= 0:
        return "-"
    change = (km - average) / average
    if change >= 0.1:
        return f"{change:+.0%}"
    if change <= -0.1:
        return f"{change:+.0%}"
    return "="


def print_history(name: str, rows: Sequence[DistanceHistoryRow]) -> None:
    if not rows:
        print(f"⚠️ No kilometres stored for {name}.")
        return

    average = sum(row.km for row in rows) / len(rows)
    print(f"🚗 {name} – {len(rows)} weeks, {average:.0f} km on average")
    print_table(
        headers=[f"{'Week':<9}", f"{'km':>6}", "Rank"],
        rows=[
            [f"{row.year}/W{row.week:02d}", f"{row.km:>6}", f"{row.rank} of {row.of}"]
            for row in rows
        ],
        width=32,
    )


def print_weeks(rows: Sequence[DistanceWeek]) -> None:
    if not rows:
        print("⚠️ No kilometres stored yet.")
        return
    print_table(
        headers=[f"{'Week':<9}", f"{'Total':>8}", f"{'Players':>8}", f"{'per head':>9}"],
        rows=[
            [
                f"{row.year}/W{row.week:02d}",
                f"{row.total:>8}",
                f"{row.players:>8}",
                f"{(row.total / row.players if row.players else 0):>9.0f}",
            ]
            for row in rows
        ],
        width=40,
    )


def print_add_result(result: AddDistanceResult, *, year: int, week: int, km: int) -> None:
    if result.status == "INVALID_RANGE":
        print("❌ Kilometres out of range.")
        return
    if result.status == "INVALID_WEEK":
        print("❌ Week must be between 1 and 53.")
        return
    if result.status == "PLAYER_NOT_FOUND":
        print("❌ Player not found.")
        return
    if result.status == "PLAYER_AMBIGUOUS":
        print("❌ Player name is ambiguous - use the id.")
        return
    print(f"✅ {result.name} ({result.player_id}): {km} km in {year} W{week:02d}")


def print_delete_result(entry_id: int, deleted: bool) -> None:
    if not deleted:
        print("❌ Distance entry not found.")
        return
    print(f"🗑️ Distance entry {entry_id} deleted.")


def print_import_result(result: ImportResult) -> None:
    if result.status == "ERRORS":
        print("❌ Import aborted due to validation errors:")
        for message in result.errors:
            print(" -", message)
        for message in result.warnings:
            print(f"⚠️  {message}")
        return

    for message in result.warnings:
        print(f"⚠️  {message}")
    if result.status == "DRY_RUN":
        print(
            f"ℹ️  Dry run: {result.year} W{result.week:02d}, {result.imported} players, "
            f"{result.total} km. Nothing written."
        )
        return
    print(f"✅ {result.year} W{result.week:02d}: {result.imported} players, {result.total} km imported")
