from __future__ import annotations

import math
import re
from typing import Any

from hcr2.services.stats import PlayerDonationSummary, PlayerStatsSummary, trend_label


PERF_TABLE_WIDTH = 31
BIRTHDAY_RE = re.compile(r"^\s*(\d{1,2})\D+(\d{1,2})\s*$")


def format_k(value: int | float | None) -> str:
    if value is None:
        return "-"
    abs_val = abs(value)
    if abs_val >= 100:
        return f"{'-' if value < 0 else ''}{round(abs_val / 1000, 1)}k"
    return f"{'-' if value < 0 else ''}0.0k"


def print_perf_table(entries: list[tuple[str, int | None, int]], *, limit: int | None = None) -> None:
    print(f"{'#':>2}   {'Lady':<14} {'Perf':>6} {'Mat.':<2}")
    print("-" * PERF_TABLE_WIDTH)
    for i, (name, delta, count) in enumerate(sorted(entries, key=lambda x: x[1] if x[1] is not None else -10**18, reverse=True), 1):
        if limit is not None and i > limit:
            break
        print(f"{i:>2}.  {name:<14} {format_k(delta):>6} {count:>2}")


def print_no_matching_season() -> None:
    print("⚠️ No matching season found.")


def print_perf_header(season_number: int, season_name: str, division: str) -> None:
    print(f"📈Performance Season {season_number} ({season_name}) DIV: {division}".rstrip())


def print_required_matches(total_matches: int, min_matches: int) -> None:
    print(f"ℹ️ Required matches: {min_matches}/{total_matches} (20%)")


def print_no_match_scores() -> None:
    print("⚠️ No match scores found.")


def print_no_active_plte_players() -> None:
    print("⚠️ No active PLTE players.")


def print_no_perf_entries(*, active_only: bool, min_matches: int) -> None:
    if active_only:
        print("⚠️ No active players with scored matches found.")
        return
    print(f"⚠️ No players with at least {min_matches} scored matches found.")


def print_aliases(aliases: list[str]) -> None:
    for alias in aliases:
        print(alias)


def print_sum_metric_header(metric: str, season_number: int, season_name: str, division: str) -> None:
    title_metric = "Score" if metric == "score" else "Points"
    print(f"📊{title_metric} Season {season_number} ({season_name}) DIV: {division}".rstrip())


def print_sum_metric_table(entries: list[tuple[str, int | None, int]], *, metric: str) -> None:
    col_label = "Score" if metric == "score" else "Pts"
    print(f"{'#':>2}   {'Lady':<14} {col_label:>6} {'Mat.':>2}")
    print("-" * PERF_TABLE_WIDTH)
    for i, (name, total, count) in enumerate(entries, 1):
        value = f"{total:>6}" if total is not None else f"{'-':>6}"
        print(f"{i:>2}.  {name:<14} {value} {count:>2}")


def print_no_data() -> None:
    print("⚠️ No data.")


def print_scatter_plot(plot: str) -> None:
    print(plot)


def print_birthday_plot(plot: str) -> None:
    print(plot)


def print_no_season() -> None:
    print("⚠️ No season.")


def print_no_matches_found() -> None:
    print("⚠️ No matches found.")


def print_no_teamevent_for_offset(offset: int) -> None:
    print(f"⚠️ No team event found for offset {offset}.")


def print_no_teamevent(te_id: int) -> None:
    print(f"⚠️ No team event with id {te_id} found.")


def print_no_teamevent_scores(te_id: int) -> None:
    print(f"⚠️ No match scores for team event {te_id}.")


def print_no_valid_teamevent_scores(te_id: int) -> None:
    print(f"⚠️ No valid scores for PLTE players in team event {te_id}.")


def print_no_teamevent_rank_data(te_id: int) -> None:
    print(f"⚠️ No data to rank for team event {te_id}.")


def print_teamevent_perf_header(te_id: int, name: str, iso_year: int, iso_week: int) -> None:
    print(f"📊 Performance Team Event {te_id}: {name} ({iso_year}-W{iso_week})")


def print_no_player(player_id: int) -> None:
    print(f"⚠️ No player with id {player_id}.")


def print_no_player_matches(player_id: int) -> None:
    print(f"⚠️ No matches found for player {player_id}.")


def print_absent_stats(season_number: int, rows: list[tuple[int, str, int]]) -> None:
    print(f"🚫 Unexcused absences (points=0, absent=0/NULL) – Season {season_number}")
    if not rows:
        print("✅ No unexcused absences.")
        return

    print(f"{'Player':<16} {'Missed':>6}")
    print("-" * 26)
    for _pid, name, count in rows:
        print(f"{name:<16} {count:>6}")


def _fmt_int(value: int | float | None) -> str:
    return "-" if value is None else str(int(value))


def _fmt_k(value: int | float | None) -> str:
    return "-" if value is None else format_k(int(round(value)))


def _print_summary_2col(title_left, title_right, rows, label_w=14, left_w=14, right_w=14):
    sep = label_w + left_w + right_w + 6
    print("-" * sep)
    print(f"{'':<{label_w}} | {title_left:<{left_w}} | {title_right:<{right_w}}")
    print("-" * sep)
    for label, lv, rv in rows:
        print(f"{label:<{label_w}} | {lv:<{left_w}} | {rv:<{right_w}}")
    print("-" * sep)


def print_player_detail(
    *,
    player_id: int,
    player_meta: tuple[Any, ...],
    last_n: int,
    last_matches: list[tuple[Any, ...]],
    summary: PlayerStatsSummary,
    total_matches_overall: int,
    donations: PlayerDonationSummary,
) -> None:
    pname, pemoji, pteam, pactive, garage_power = player_meta
    pemoji = (pemoji or "").strip()
    try:
        garage_power = int(garage_power or 0)
    except Exception:
        garage_power = 0

    head = f"👤 {player_id}: {pname}"
    if pemoji:
        head += f" {pemoji}"
    head += f" (GP {garage_power}, {pteam or '-'}, act {int(bool(pactive))})"
    print(head)

    print(f"{'#':>2} {'Date':<10} {'S':>3} {'M':>5} {'Event':<14} {'Sc':>5} {'Pt':>3} {'Pf':>6}")
    print("-" * 56)

    for i, (mid, start, season, te_name, _tracks, score, points, _absent) in enumerate(last_matches, 1):
        start_s = (start or "")[:10]
        te_short = (te_name or "")[:14]
        score_s = "-" if score is None else str(int(score))
        pts_s = "-" if points is None else str(int(points))

        if mid in summary.last_perf_by_match:
            delta = summary.last_perf_by_match[mid]
            perf_str = _fmt_k(delta) if delta is not None else "n/a"
        else:
            perf_str = "-"

        print(f"{i:>2} {start_s:<10} {season:>3} {mid:>5} {te_short:<14} {score_s:>5} {pts_s:>3} {perf_str:>6}")

    rows = [
        ("Matches", _fmt_int(summary.last_counted), _fmt_int(total_matches_overall)),
        ("Unexcused", _fmt_int(summary.last_unexcused), _fmt_int(summary.overall_unexcused)),
        (
            "Avg score",
            _fmt_int(round(summary.last_avg_score)) if summary.last_avg_score is not None else "-",
            _fmt_int(round(summary.overall_avg_score)) if summary.overall_avg_score is not None else "-",
        ),
        (
            "Avg pts",
            _fmt_int(round(summary.last_avg_points)) if summary.last_avg_points is not None else "-",
            _fmt_int(round(summary.overall_avg_points)) if summary.overall_avg_points is not None else "-",
        ),
        ("Avg perf", _fmt_k(summary.last_avg_perf), _fmt_k(summary.overall_avg_perf)),
        ("Trend(-3..+3)", trend_label(summary.last_trend), trend_label(summary.overall_trend)),
    ]
    _print_summary_2col(f"last {last_n}", "overall", rows)

    print(f"\n📦 Donations since {donations.start_date}" + (f" → {donations.cutoff_date}" if donations.cutoff_date else ""))
    print(f"{'Mch':>3} {'Exp':>7} {'Tot':>7} {'Idx':>5}")
    print(f"{donations.matches:3d} {format_k(donations.expected):>7} {format_k(donations.total):>7} {donations.index:5.1f}")


def print_battle_plot(
    *,
    name1: str,
    emoji1: str,
    name2: str,
    emoji2: str,
    season_number: int,
    match_ids: list[int],
    scores: dict[tuple[int, int], int],
    player1_id: int,
    player2_id: int,
    height: int = 30,
    col_width: int = 3,
) -> None:
    vals = list(scores.values())
    if not vals:
        print("⚠️ No scores for these players in this season.")
        return

    cw = max(2, int(col_width))
    vmin, vmax = min(vals), max(vals)
    if vmin == vmax:
        vmin = max(0, vmin - 1000)
        vmax = vmax + 1000
    pad = max(500, int(0.05 * (vmax - vmin)))
    vmin = max(0, (vmin - pad) // 1000 * 1000)
    vmax = math.ceil((vmax + pad) / 1000) * 1000

    def y_to_row(value: int) -> int:
        ratio = (value - vmin) / (vmax - vmin) if vmax > vmin else 0.5
        return int(round(ratio * (height - 1)))

    plot_w = len(match_ids) * cw
    grid = [[" "] * plot_w for _ in range(height)]

    def place_cell(row_idx: int, col_x: int, text: str) -> None:
        cell_text = (text or "")[:cw]
        leftpad = (cw - len(cell_text)) // 2
        cell = (" " * leftpad + cell_text).ljust(cw, " ")
        for k, char in enumerate(cell):
            pos = col_x + k
            if 0 <= pos < plot_w:
                grid[row_idx][pos] = char

    for x, match_id in enumerate(match_ids):
        col = x * cw
        here = []
        score1 = scores.get((match_id, player1_id))
        if score1 is not None:
            here.append((height - 1 - y_to_row(score1), emoji1))
        score2 = scores.get((match_id, player2_id))
        if score2 is not None:
            here.append((height - 1 - y_to_row(score2), emoji2))

        if len(here) == 2 and here[0][0] == here[1][0]:
            place_cell(here[0][0], col, (here[0][1] + here[1][1])[:cw])
        else:
            for row_idx, mark in here:
                place_cell(row_idx, col, mark)

    tick_rows = {0, height // 4, height // 2, (3 * height) // 4, height - 1}

    print(f"Battle {name1} {emoji1} vs {name2} {emoji2} (Season {season_number})")
    for row in range(height):
        if row in tick_rows:
            value = vmax - (vmax - vmin) * (row / (height - 1))
            label = f"{int(round(value / 1000))}k".rjust(4)
        else:
            label = " " * 4
        print(f"{label}│{''.join(grid[row])}")

    print(" " * 4 + "└" + "─" * plot_w)
    labels = "".join(f"{i + 1:>{cw}}" for i in range(len(match_ids)))
    print(" " * 5 + labels)


def scatter_fixed(
    rows,
    *,
    width: int = 70,
    height: int = 35,
    x_labels: int = 6,
    symbol: str | None = None,
    title: str = "Avg score per season (scaled)",
) -> str:
    if not rows:
        return "```No data.```"
    symbol = "."

    def format_axis_k(value: float) -> str:
        return f"{int(round(value / 1000.0))}k"

    seasons = [int(season) for season, _ in rows]
    values = [float(value) for _, value in rows]
    count = len(seasons)

    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        vmax = vmin + 1.0

    gutter = 9
    plot_cols = max(10, width - gutter)
    col_idx = [0] * count
    if count == 1:
        col_idx[0] = plot_cols - 1
    else:
        for i in range(count):
            col_idx[i] = round(i * (plot_cols - 1) / (count - 1))

    def to_level(value: float) -> int:
        ratio = (value - vmin) / (vmax - vmin)
        return int(round(ratio * (height - 1)))

    y_levels = [to_level(value) for value in values]
    lines = [f"{title} (min={int(vmin)}, max={int(vmax)})"]

    for row_level in range(height - 1, -1, -1):
        if row_level in {height - 1, (height - 1) // 2, 0}:
            y_val = vmin + (vmax - vmin) * (row_level / (height - 1))
            y_label = format_axis_k(y_val).rjust(6)
            left = f"{y_label} │ "
        else:
            left = " " * (gutter - 2) + "│ "

        row = [" "] * plot_cols
        for col, level in zip(col_idx, y_levels):
            if level == row_level and 0 <= col < plot_cols:
                row[col] = symbol
        lines.append(left + "".join(row))

    lines.append(" " * (gutter - 2) + "└" + "─" * plot_cols)

    if x_labels < 2:
        x_labels = 2
    label_positions = [round(j * (plot_cols - 1) / (x_labels - 1)) for j in range(x_labels)]
    label_indices = [round(j * (count - 1) / (x_labels - 1)) for j in range(x_labels)]

    label_buffer = [" "] * plot_cols
    for pos, idx in zip(label_positions, label_indices):
        label = f"S{seasons[idx]}"
        start = min(max(0, pos - len(label) // 2), max(0, plot_cols - len(label)))
        for offset, char in enumerate(label):
            p = start + offset
            if 0 <= p < plot_cols:
                label_buffer[p] = char

    lines.append(" " * gutter + "".join(label_buffer).rstrip())
    return "```\n" + "\n".join(lines) + "\n```"


def birthday_plot(rows, *, width: int = 77, height: int = 31, cols_per_month: int = 2, cell_w: int = 2) -> str:
    assert height == 31, "height must be 31"
    months = 12
    gutter = 5

    plot_cols = months * cols_per_month * cell_w
    cells_per_row = plot_cols // cell_w

    grid = [[" " * cell_w for _ in range(cells_per_row)] for _ in range(height)]
    slots = {(month + 1, day + 1): 0 for month in range(months) for day in range(height)}

    for _name, birthday, emoji in rows:
        value = (birthday or "").strip()
        match = BIRTHDAY_RE.match(value)
        if not match:
            continue
        a, b = int(match.group(1)), int(match.group(2))
        if 1 <= a <= 12 and 1 <= b <= 31:
            month, day = a, b
        elif 1 <= b <= 12 and 1 <= a <= 31:
            month, day = b, a
        else:
            continue

        if not (1 <= day <= 31 and 1 <= month <= 12):
            continue
        symbol = emoji.strip()
        if not symbol:
            continue

        row = day - 1
        month_cell0 = (month - 1) * cols_per_month
        slot = slots[(month, day)]
        cell_idx = month_cell0 + (slot if slot < cols_per_month else cols_per_month - 1)
        if slot < cols_per_month:
            slots[(month, day)] = slot + 1
        grid[row][cell_idx] = symbol

    lines = ["Power Ladies Birthday Map"]
    for row in range(height - 1, -1, -1):
        lines.append(f"{row + 1:02d} │ " + "".join(grid[row]))

    lines.append(" " * (gutter - 2) + "└" + "─" * plot_cols)

    label_cells = [" "] * cells_per_row
    for month in range(1, months + 1):
        center_cell = (month - 1) * cols_per_month + (cols_per_month // 2)
        label_cells[center_cell] = str(month)
    label_line = "".join(label.center(cell_w) for label in label_cells)
    lines.append(" " * gutter + label_line.rstrip())

    return "```\n" + "\n".join(lines) + "\n```"
