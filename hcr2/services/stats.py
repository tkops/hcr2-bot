from __future__ import annotations

from dataclasses import dataclass
import statistics
from typing import Any


def is_absent(score: int | None, points: int | None, absent_flag: int | None) -> bool:
    if score is not None and score > 0:
        return False
    if absent_flag is not None:
        return bool(absent_flag) and (score is None or score == 0)
    return (points is not None and points == 0) and (score is None or score == 0)


def is_active_plte(active: Any, team: str | None) -> bool:
    return bool(active) and bool(team) and team.upper() == "PLTE"


def scaled_score(score: int, tracks: int | None) -> float:
    return score * 4 / tracks if tracks else score


def append_scored_match(
    scores_by_match: dict[int, list[tuple[int, str, float]]],
    match_id: int,
    player_id: int,
    label: str,
    score: int,
    tracks: int | None,
) -> None:
    scores_by_match.setdefault(match_id, []).append((player_id, label, scaled_score(score, tracks)))


def calculate_match_deltas(
    scores_by_match: dict[int, list[tuple[int, str, float]]],
) -> tuple[dict[int, list[float]], dict[int, str], dict[int, int]]:
    player_scores: dict[int, list[float]] = {}
    player_labels: dict[int, str] = {}
    player_counts: dict[int, int] = {}

    for entries in scores_by_match.values():
        scores = [score for _, _, score in entries]
        if not scores:
            continue
        try:
            median = statistics.median(scores)
        except statistics.StatisticsError:
            continue

        for player_id, label, score in entries:
            player_scores.setdefault(player_id, []).append(score - median)
            player_labels[player_id] = label
            player_counts[player_id] = player_counts.get(player_id, 0) + 1

    return player_scores, player_labels, player_counts


def build_delta_entries(
    player_scores: dict[int, list[float]],
    player_labels: dict[int, str],
    player_counts: dict[int, int],
    min_count: int = 0,
) -> list[tuple[str, int, int]]:
    entries: list[tuple[str, int, int]] = []
    for player_id, deltas in player_scores.items():
        count = player_counts.get(player_id, 0)
        if count < min_count:
            continue
        avg_delta = round(sum(deltas) / len(deltas))
        entries.append((player_labels[player_id], avg_delta, count))
    return entries


def sorted_delta_entries(entries: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    return sorted(entries, key=lambda entry: entry[1], reverse=True)


def linreg_slope(values: list[float]) -> float:
    count = len(values)
    if count < 2:
        return 0.0
    x_mean = (count - 1) / 2.0
    y_mean = sum(values) / count
    numerator = denominator = 0.0
    for index, value in enumerate(values):
        dx = index - x_mean
        dy = value - y_mean
        numerator += dx * dy
        denominator += dx * dx
    return numerator / denominator if denominator else 0.0


def trend_to_score(slope: float) -> int:
    if slope <= -150:
        return -3
    if slope <= -75:
        return -2
    if slope <= -25:
        return -1
    if slope < 25:
        return 0
    if slope < 75:
        return 1
    if slope < 150:
        return 2
    return 3


def trend_label(trend: int) -> str:
    if trend <= -3:
        return "↓-3"
    if trend == -2:
        return "↓-2"
    if trend == -1:
        return "↘-1"
    if trend == 0:
        return "→0"
    if trend == 1:
        return "↗+1"
    if trend == 2:
        return "↑+2"
    return "↑+3"


def is_unexcused_absence(score: int | None, points: int | None, absent: int | None) -> bool:
    return (
        (score is None or score == 0)
        and (points is None or points == 0)
        and (absent is None or absent == 0)
    )


def calculate_match_medians(rows: list[tuple[Any, ...]]) -> dict[int, float]:
    values_by_match: dict[int, list[float]] = {}
    for match_id, score, points, absent, team, tracks in rows:
        if not team or team.upper() != "PLTE":
            continue
        if score is None or is_absent(score, points, absent):
            continue
        values_by_match.setdefault(match_id, []).append(float(scaled_score(score, tracks)))

    return {
        match_id: statistics.median(values)
        for match_id, values in values_by_match.items()
        if values
    }


@dataclass(frozen=True)
class PlayerStatsSummary:
    last_counted: int
    last_unexcused: int
    last_avg_score: float | None
    last_avg_points: float | None
    last_avg_perf: float | None
    last_trend: int
    overall_counted: int
    overall_unexcused: int
    overall_avg_score: float | None
    overall_avg_points: float | None
    overall_avg_perf: float | None
    overall_trend: int
    last_perf_by_match: dict[int, int | None]


@dataclass(frozen=True)
class PlayerDonationSummary:
    start_date: str
    cutoff_date: str | None
    matches: int
    expected: int
    total: int
    index: float


def summarize_player_stats(
    last_matches: list[tuple[Any, ...]],
    overall_matches: list[tuple[Any, ...]],
    medians_by_match: dict[int, float],
    *,
    total_unexcused_overall: int,
) -> PlayerStatsSummary:
    last_counted = 0
    last_unexcused = 0
    last_score_sum = 0
    last_points_sum = 0
    last_deltas_avg: list[int] = []
    last_deltas_desc: list[float] = []
    last_perf_by_match: dict[int, int | None] = {}

    for mid, _start, _season, _te_name, tracks, score, points, absent in last_matches:
        if is_unexcused_absence(score, points, absent):
            last_unexcused += 1

        if score is None or is_absent(score, points, absent):
            continue

        scaled = scaled_score(score, tracks)
        med = medians_by_match.get(mid)
        if med is not None:
            delta = round(scaled - med)
            last_perf_by_match[mid] = delta
            last_deltas_avg.append(delta)
            last_deltas_desc.append(float(scaled - med))
        else:
            last_perf_by_match[mid] = None

        last_counted += 1
        last_score_sum += int(score)
        last_points_sum += int(points or 0)

    overall_counted = 0
    overall_score_sum = 0
    overall_points_sum = 0
    overall_deltas: list[float] = []

    for mid, _start, tracks, score, points, absent in overall_matches:
        if score is None or is_absent(score, points, absent):
            continue

        overall_counted += 1
        overall_score_sum += int(score)
        overall_points_sum += int(points or 0)

        med = medians_by_match.get(mid)
        if med is None:
            continue
        overall_deltas.append(float(scaled_score(score, tracks) - med))

    last_deltas_trend = list(reversed(last_deltas_desc))

    return PlayerStatsSummary(
        last_counted=last_counted,
        last_unexcused=last_unexcused,
        last_avg_score=(last_score_sum / last_counted) if last_counted else None,
        last_avg_points=(last_points_sum / last_counted) if last_counted else None,
        last_avg_perf=(sum(last_deltas_avg) / len(last_deltas_avg)) if last_deltas_avg else None,
        last_trend=trend_to_score(linreg_slope(last_deltas_trend) if last_deltas_trend else 0.0),
        overall_counted=overall_counted,
        overall_unexcused=total_unexcused_overall,
        overall_avg_score=(overall_score_sum / overall_counted) if overall_counted else None,
        overall_avg_points=(overall_points_sum / overall_counted) if overall_counted else None,
        overall_avg_perf=(sum(overall_deltas) / len(overall_deltas)) if overall_deltas else None,
        overall_trend=trend_to_score(linreg_slope(overall_deltas) if overall_deltas else 0.0),
        last_perf_by_match=last_perf_by_match,
    )


def summarize_player_donations(
    *,
    start_date: str,
    cutoff_date: str | None,
    matches: int,
    total: int,
    expected_per_match: int = 600,
) -> PlayerDonationSummary:
    expected = matches * expected_per_match if cutoff_date is not None else 0
    total = total if cutoff_date is not None else 0
    matches = matches if cutoff_date is not None else 0
    index = (total / expected * 100.0) if expected > 0 else 0.0
    return PlayerDonationSummary(
        start_date=start_date,
        cutoff_date=cutoff_date,
        matches=matches,
        expected=expected,
        total=total,
        index=index,
    )
