#!/usr/bin/env python3
from typing import Callable, Optional

from hcr2.output import stats as stats_output
from hcr2.repositories import stats as stats_repo
from hcr2.services import stats as stats_service
from modules.common import is_help_request, parse_int, print_command_help, print_unknown_command

PERF_TABLE_WIDTH = 31
PERF_TABLE_LIMIT = 50

# ---------------------------------------------------------------------------

def handle_command(cmd, args):
    if is_help_request(cmd, *args):
        print_help()
        return

    handlers: dict[str, Callable[[list[str]], None]] = {
        "avg": _handle_avg,
        "alias": _handle_alias,
        "rank": _handle_rank,
        "perf": _handle_perf,
        "scatter": _handle_scatter,
        "bdayplot": _handle_bdayplot,
        "battle": _handle_battle,
        "absent": _handle_absent,
        "te": _handle_te,
        "te-user": _handle_te_user,
        "score": _handle_score,
        "points": _handle_points,
        "player": _handle_player,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print_unknown_command("stats", cmd)
        print_help()
        return
    handler(args)


def _single_optional_int_arg(args, usage: str) -> Optional[int]:
    if not args:
        return None
    value = parse_int(args[0], default=None)
    if value is None:
        print(usage)
        return None
    return value


def _handle_avg(args):
    if args:
        season_arg = _single_optional_int_arg(args, "Usage: stats avg [season]")
        if season_arg is None:
            return
    else:
        season_arg = None
    show_average(season_arg)


def _handle_alias(args):
    if args:
        print("Usage: stats alias")
        return
    show_plte_alias()


def _handle_rank(args):
    if args:
        season_arg = _single_optional_int_arg(args, "Usage: stats rank [season]")
        if season_arg is None:
            return
    else:
        season_arg = None
    rank_active_plte(season_arg)


def _handle_perf(args):
    show_perf(args)


def _handle_scatter(args):
    if args:
        n = _single_optional_int_arg(args, "Usage: stats scatter [N]")
        if n is None:
            return
    else:
        n = 20
    show_season_score_scatter(last_n=n, height=12, symbol="🔵")


def _handle_bdayplot(args):
    if args:
        print("Usage: stats bdayplot")
        return
    show_birthday_plot(width=32, height=31, cols_per_month=1)


def _handle_battle(args):
    if len(args) < 2:
        print("Usage: stats battle <id1> <id2> [season]")
        return
    player1_id = parse_int(args[0], default=None)
    player2_id = parse_int(args[1], default=None)
    season_number = parse_int(args[2], default=None) if len(args) > 2 else None
    if player1_id is None or player2_id is None or (len(args) > 2 and season_number is None):
        print("Usage: stats battle <id1> <id2> [season]")
        return
    show_battle(player1_id, player2_id, season_number)


def _handle_absent(args):
    if args:
        season_arg = _single_optional_int_arg(args, "Usage: stats absent [season]")
        if season_arg is None:
            return
    else:
        season_arg = None
    show_absent(season_arg)


def _handle_te(args):
    if not args:
        print("Usage: stats te <team_event_id>")
        return
    te_id = parse_int(args[0], default=None)
    if te_id is None:
        print("Usage: stats te <team_event_id>")
        return
    show_teamevent_stats(te_id)


def _handle_te_user(args):
    if args:
        offset = _single_optional_int_arg(args, "Usage: stats te-user [n]")
        if offset is None:
            return
    else:
        offset = 0
    show_teamevent_stats_user(offset)


def _handle_score(args):
    show_score(args)


def _handle_points(args):
    show_points(args)


def _handle_player(args):
    if not args:
        print("Usage: stats player <player_id> [N]")
        return
    player_id = parse_int(args[0], default=None)
    last_n = parse_int(args[1], default=None) if len(args) > 1 else 15
    if player_id is None or (len(args) > 1 and last_n is None):
        print("Usage: stats player <player_id> [N]")
        return
    show_player_last_matches(player_id, last_n=last_n)

def print_help():
    print_command_help(
        usage="hcr2.py stats <command> [options]",
        commands=[
            ("perf [season] [--active]", "Show performance ranking"),
            ("avg [season]", "Show legacy averages for current or given season"),
            ("alias", "Show aliases of active PLTE players sorted by rank"),
            ("rank [season]", "Show legacy rank of all active PLTE players"),
            ("te <teamevent_id>", "Show rank stats for one team event"),
            ("te-user [n]", "Show relative team-event stats: 0=current, 1=last, 2=previous"),
            ("scatter [N]", "Show average score plot for the last N seasons"),
            ("bdayplot", "Show birthday plot"),
            ("battle <id1> <id2> [season]", "Compare season stats"),
            ("absent [season]", "Show absent stats"),
            ("player <id> [N]", "Show the last matches for one player"),
            ("score [season] [--skip|--no-skip]", "Show sum of scores per player in season"),
            ("points [season] [--skip|--no-skip]", "Show sum of points per player in season"),
        ],
        notes=[
            "perf defaults to players with at least 20% scored matches in season.",
            "perf --active shows only active PLTE players with more than 0 scored matches.",
            "score and points default to scored active PLTE players.",
        ],
    )

# ---------------------------------------------------------------------------

def format_k(value):
    return stats_output.format_k(value)

def find_current_season(cur):
    return stats_repo.find_current_season()

def _get_season_meta(cur, season_number):
    """
    Return (name, division) for the season.
    Return empty strings if the columns do not exist.
    """
    return stats_repo.get_season_meta(season_number)

def _fetch_season_rows(cur, season_number):
    """
    Fetch all relevant season rows including points and absent.
    """
    return stats_repo.fetch_season_rows(season_number)

def _get_min_required_matches(cur, season_number, ratio=0.20):
    """
    Minimum scored matches for stats perf.
    Example:
      15 Matches in Season -> ceil(15 * 0.20) = 3
    """
    return stats_repo.get_min_required_matches(season_number, ratio=ratio)

def _is_absent(score, points, absent_flag):
    return stats_service.is_absent(score, points, absent_flag)

def _is_active_plte(active, team):
    return stats_service.is_active_plte(active, team)

def _scaled_score(score, tracks):
    return stats_service.scaled_score(score, tracks)

def _append_scored_match(scores_by_match, match_id, pid, label, score, tracks):
    stats_service.append_scored_match(scores_by_match, match_id, pid, label, score, tracks)

def _calculate_match_deltas(scores_by_match):
    return stats_service.calculate_match_deltas(scores_by_match)

def _build_delta_entries(player_scores, player_labels, player_counts, min_count=0):
    return stats_service.build_delta_entries(player_scores, player_labels, player_counts, min_count)

def _sorted_delta_entries(entries):
    return stats_service.sorted_delta_entries(entries)

def _print_perf_table(entries, limit=None):
    stats_output.print_perf_table(_sorted_delta_entries(entries), limit=limit)

# ---------------------------------------------------------------------------

def show_average(season_number=None, active_only=False):
    """
    Default:
      - all players with at least 20% scored matches in the season
      - regardless of whether they are still active / in PLTE

    --active:
      - only currently active PLTE players
      - then all with >0 scored matches
    """
    if season_number is None:
        season_number = find_current_season(None)
    if not season_number:
        print("⚠️ No matching season found.")
        return

    s_name, s_div = _get_season_meta(None, season_number)
    header_line = f"📈Performance Season {season_number} ({s_name}) DIV: {s_div}".rstrip()
    print(header_line)

    if not active_only:
        total_matches, min_matches = _get_min_required_matches(None, season_number, ratio=0.20)
        print(f"ℹ️ Required matches: {min_matches}/{total_matches} (20%)")
    else:
        total_matches = 0
        min_matches = 1

    rows = _fetch_season_rows(None, season_number)
    if not rows:
        print("⚠️ No match scores found.")
        return

    # Scores grouped by match.
    scores_by_match = {}
    for pid, name, alias, team, active, score, points, absent, match_id, tracks, max_score in rows:
        if score is None or _is_absent(score, points, absent):
            continue

        # Limit to current active PLTE players only for --active.
        if active_only and not _is_active_plte(active, team):
            continue

        _append_scored_match(scores_by_match, match_id, pid, name, score, tracks)

    if not scores_by_match:
        print("⚠️ No match scores found.")
        return

    player_scores, player_names, player_counts = _calculate_match_deltas(scores_by_match)
    entries = _build_delta_entries(player_scores, player_names, player_counts, min_matches)

    if not entries:
        if active_only:
            print("⚠️ No active players with scored matches found.")
        else:
            print(f"⚠️ No players with at least {min_matches} scored matches found.")
        return

    _print_perf_table(entries, limit=PERF_TABLE_LIMIT)

# ---------------------------------------------------------------------------

def show_plte_alias():
    season_number = find_current_season(None)
    if not season_number:
        return

    rows = _fetch_season_rows(None, season_number)
    if not rows:
        return

    scores_by_match = {}
    for pid, name, alias, team, active, score, points, absent, match_id, tracks, max_score in rows:
        if team != "PLTE" or score is None or _is_absent(score, points, absent):
            continue
        _append_scored_match(scores_by_match, match_id, pid, alias, score, tracks)

    player_scores, player_alias, _player_counts = _calculate_match_deltas(scores_by_match)

    active_ids = stats_repo.list_active_plte_player_ids()

    entries = []
    for pid, deltas in player_scores.items():
        if pid not in active_ids:
            continue
        avg_delta = round(sum(deltas) / len(deltas))
        entries.append((player_alias[pid], avg_delta))

    for alias, _ in sorted(entries, key=lambda x: x[1], reverse=True):
        print(alias)

# ---------------------------------------------------------------------------

def rank_active_plte(season_number=None):
    """
    Rank ALL active PLTE players:
    - Avg delta vs. median per match (scaled to 4 tracks), same as `avg`
    - No 80% filter
    - Players without scores at the end
    """
    if season_number is None:
        season_number = find_current_season(None)
    if not season_number:
        print("⚠️ No matching season found.")
        return

    # All active PLTE players.
    active_players = stats_repo.list_active_plte_players()
    if not active_players:
        print("⚠️ No active PLTE players.")
        return
    id_to_name = {pid: name for pid, name in active_players}

    rows = _fetch_season_rows(None, season_number)

    scores_by_match = {}
    for pid, name, alias, team, active, score, points, absent, match_id, tracks, max_score in rows:
        if team != "PLTE" or not active:
            continue
        if score is None or _is_absent(score, points, absent):
            continue
        _append_scored_match(scores_by_match, match_id, pid, name, score, tracks)

    player_scores, _player_names, player_counts = _calculate_match_deltas(scores_by_match)

    with_scores = []
    without_scores = []
    for pid, name in id_to_name.items():
        deltas = player_scores.get(pid)
        if deltas:
            avg_delta = round(sum(deltas) / len(deltas))
            count = player_counts.get(pid, 0)
            with_scores.append((name, avg_delta, count))
        else:
            without_scores.append((name, None, 0))

    with_scores_sorted = sorted(with_scores, key=lambda x: x[1], reverse=True)
    without_scores_sorted = sorted(without_scores, key=lambda x: x[0].lower())
    entries = with_scores_sorted + without_scores_sorted

    print(f"{'#':>2}   {'Lady':<14} {'Perf':>6} {'Mat.':<2}")
    print("-" * PERF_TABLE_WIDTH)
    for i, (name, delta, count) in enumerate(entries, 1):
        print(f"{i:>2}.  {name:<14} {format_k(delta):>6} {count:>2}")

# ---------------------------------------------------------------------------
# Wrapper: stats perf
# ---------------------------------------------------------------------------

def show_perf(args):
    """
    stats perf [season] [--active]

    default:
      - all players with at least 20% matches in the season
      - regardless of current active/team status

    --active:
      - only currently active PLTE players
      - all with >0 matches
    """
    season_number = None
    active_only = False

    for a in args:
        if a == "--active":
            active_only = True
        else:
            try:
                season_number = int(a)
            except ValueError:
                print("Usage: stats perf [season] [--active]")
                return

    show_average(season_number, active_only=active_only)

# ---------------------------------------------------------------------------
# Wrapper: stats score / stats points
# ---------------------------------------------------------------------------

def show_score(args):
    """
    stats score [season] [--skip|--no-skip]
      --skip / default   -> only active PLTE with scored participation (not absent), sum of scores
      --no-skip          -> all active PLTE players, no-score entries at the bottom
    """
    season_number = None
    skip = True  # default

    for a in args:
        if a == "--no-skip":
            skip = False
        elif a == "--skip":
            skip = True
        else:
            try:
                season_number = int(a)
            except ValueError:
                print("Usage: stats score [season] [--skip|--no-skip]")
                return

    _rank_sum_metric(season_number, metric="score", skip=skip)

def show_points(args):
    """
    stats points [season] [--skip|--no-skip]
      --skip / default   -> only active PLTE with scored participation (not absent), sum of points
      --no-skip          -> all active PLTE players, no-points entries at the bottom
    """
    season_number = None
    skip = True  # default

    for a in args:
        if a == "--no-skip":
            skip = False
        elif a == "--skip":
            skip = True
        else:
            try:
                season_number = int(a)
            except ValueError:
                print("Usage: stats points [season] [--skip|--no-skip]")
                return

    _rank_sum_metric(season_number, metric="points", skip=skip)

def _rank_sum_metric(season_number=None, metric="score", skip=True):
    """
    Aggregate and rank sums per player for one season.
    metric: "score" or "points"
    skip=True  : only active PLTE with scored participation (not absent)
    skip=False : all active PLTE players; players without participation/metric at the bottom
    """
    assert metric in {"score", "points"}, "metric must be 'score' or 'points'"

    if season_number is None:
        season_number = find_current_season(None)
    if not season_number:
        print("⚠️ No matching season found.")
        return

    # Header metadata.
    s_name, s_div = _get_season_meta(None, season_number)
    title_metric = "Score" if metric == "score" else "Points"
    header_line = f"📊{title_metric} Season {season_number} ({s_name}) DIV: {s_div}".rstrip()
    print(header_line)

    # Active PLTE players for name lookup and the no-skip list.
    active_players = stats_repo.list_active_plte_players()
    if not active_players:
        print("⚠️ No active PLTE players.")
        return
    id_to_name = {pid: name for pid, name in active_players}

    rows = _fetch_season_rows(None, season_number)
    if not rows:
        print("⚠️ No match scores found.")
        return

    totals = {}   # pid -> sum (score/points)
    counts = {}   # pid -> number of matches with scored participation
    name_by_id = {}  # pid -> name (fallback)

    for pid, name, alias, team, active, score, points, absent, match_id, tracks, max_score in rows:
        # Include only PLTE and active players in both modes.
        if not _is_active_plte(active, team):
            continue

        # Count participation only when not absent.
        if _is_absent(score, points, absent):
            continue

        # Extract the selected metric.
        if metric == "score":
            if score is None:
                continue  # Nothing to sum here without a score.
            value = int(score)
        else:  # metric == "points"
            value = int(points or 0)

        totals[pid] = totals.get(pid, 0) + value
        counts[pid] = counts.get(pid, 0) + 1
        name_by_id[pid] = name

    if skip:
        # Print only players with participation/metric, sorted by sum.
        entries = []
        for pid, total in totals.items():
            pname = id_to_name.get(pid, name_by_id.get(pid, f"ID {pid}"))
            cnt = counts.get(pid, 0)
            entries.append((pname, total, cnt))

        entries.sort(key=lambda x: x[1], reverse=True)

        stats_output.print_sum_metric_table(entries, metric=metric)

    else:
        # All active PLTE players, with missing values alphabetically at the bottom.
        with_vals = []
        without_vals = []
        for pid, pname in id_to_name.items():
            if pid in totals:
                with_vals.append((pname, totals[pid], counts.get(pid, 0)))
            else:
                without_vals.append((pname, None, 0))

        with_vals.sort(key=lambda x: x[1], reverse=True)
        without_vals.sort(key=lambda x: x[0].lower())
        entries = with_vals + without_vals

        stats_output.print_sum_metric_table(entries, metric=metric)

# ---------------------------------------------------------------------------

def _fetch_avg_score_last_seasons(cur, last_n=20):
    return stats_repo.fetch_avg_score_last_seasons(last_n)

def _format_k(v):
    return f"{int(round(v/1000.0))}k"

def _scatter_fixed(rows, width=70, height=35, x_labels=6, symbol=None,
                   title="Avg score per season (scaled)"):
    return stats_output.scatter_fixed(rows, width=width, height=height, x_labels=x_labels, symbol=symbol, title=title)

def show_season_score_scatter(last_n=20, height=35, width=70, x_labels=6, symbol="."):
    rows = _fetch_avg_score_last_seasons(None, last_n=last_n)
    if not rows:
        print("⚠️ No data.")
        return
    print(_scatter_fixed(rows, width=width, height=height, x_labels=x_labels, symbol=symbol))

# ---------------------------------------------------------------------------

def show_birthday_plot(width=77, height=31, cols_per_month=2, cell_w=2):
    """
    31 rows (days 1..31, top=31). 12 months, each with 3 cells of 2 columns.
    Uses the exact emoji from players.emoji.
    """
    print(stats_output.birthday_plot(stats_repo.fetch_birthday_plot_rows(), width=width, height=height, cols_per_month=cols_per_month, cell_w=cell_w))

# ---------------------------------------------------------------------------

def show_battle(player1_id, player2_id, season_number=None, height=30, max_matches=15, col_width=3):
    """
    Battle plot for two players in one season.
    Absent players are not plotted.
    """
    if season_number is None:
        season_number = find_current_season(None)
        if not season_number:
            print("⚠️ No season.")
            return

    matches = stats_repo.fetch_season_matches(season_number)
    if not matches:
        print("⚠️ No matches found.")
        return

    matches = matches[-max_matches:]
    match_ids = [mid for mid, _ in matches]

    meta = stats_repo.fetch_player_meta_for_ids(player1_id, player2_id)

    name1, emo1 = meta.get(player1_id, (f"ID {player1_id}", ""))
    name2, emo2 = meta.get(player2_id, (f"ID {player2_id}", ""))

    if not emo1.strip():
        emo1 = "🅰️"
    if not emo2.strip():
        emo2 = "🅱️"

    rows = stats_repo.fetch_matchscores_for_matches_players(match_ids, player1_id, player2_id)

    scores = {}
    for mid, pid, score, points, absent in rows:
        if score is None or _is_absent(score, points, absent):
            continue
        scores[(mid, pid)] = score

    stats_output.print_battle_plot(
        name1=name1,
        emoji1=emo1,
        name2=name2,
        emoji2=emo2,
        season_number=season_number,
        match_ids=match_ids,
        scores=scores,
        player1_id=player1_id,
        player2_id=player2_id,
        height=height,
        col_width=col_width,
    )

def show_absent(season_number=None):
    """
    Show unexcused absences for active PLTE players:
    (absent IS NULL or 0) AND points = 0
    """
    if season_number is None:
        season_number = find_current_season(None)
    if not season_number:
        print("⚠️ No matching season found.")
        return

    rows = stats_repo.fetch_unexcused_absences(season_number)

    stats_output.print_absent_stats(season_number, rows)

# ---------------------------------------------------------------------------

def _resolve_teamevent_by_offset(cur, offset: int):
    """
    offset 0 = current/latest team event with matches,
    1 = previous event, 2 = event before that, etc.
    Sorted by iso_year/iso_week descending, with id as fallback.
    """
    return stats_repo.resolve_teamevent_by_offset(offset)

def show_teamevent_stats_user(offset: int = 0):
    """
    Wrapper for show_teamevent_stats with a relative index:
    offset 0 = current/latest team event, 1 = previous event, ...
    """
    te_id = _resolve_teamevent_by_offset(None, offset)

    if te_id is None:
        print(f"⚠️ No team event found for offset {offset}.")
        return

    show_teamevent_stats(te_id)

# ---------------------------------------------------------------------------

def show_teamevent_stats(te_id):
    """
    Rank stats for a single team event:
    - Uses avg delta vs. median per match (scaled to 4 tracks), same logic as avg/rank
    - All PLTE players who have at least one score in that event (regardless of current 'active' flag)
    """
    # Fetch team event metadata.
    row = stats_repo.get_teamevent_meta(te_id)
    if not row:
        print(f"⚠️ No team event with id {te_id} found.")
        return

    te_name, iso_year, iso_week, te_tracks, te_max = row

    # Fetch all matches for this team event, including scores.
    rows = stats_repo.fetch_teamevent_rows(te_id)

    if not rows:
        print(f"⚠️ No match scores for team event {te_id}.")
        return

    # Scores per match: all PLTE, not absent; active is intentionally not filtered here.
    scores_by_match = {}
    for pid, name, team, active, score, points, absent, match_id, tracks, max_score in rows:
        if not team or team.upper() != "PLTE":
            continue
        if score is None or _is_absent(score, points, absent):
            continue

        _append_scored_match(scores_by_match, match_id, pid, name, score, tracks)

    if not scores_by_match:
        print(f"⚠️ No valid scores for PLTE players in team event {te_id}.")
        return

    # Deltas vs. median per match.
    player_scores, player_names, player_counts = _calculate_match_deltas(scores_by_match)

    if not player_scores:
        print(f"⚠️ No data to rank for team event {te_id}.")
        return

    # Build result entries.
    entries = _build_delta_entries(player_scores, player_names, player_counts)

    # Header.
    print(f"📊 Performance Team Event {te_id}: {te_name} ({iso_year}-W{iso_week})")
    _print_perf_table(entries)

def show_player_last_matches(player_id: int, last_n: int = 15):
    """
    Compact output (Discord-friendly):
    - Last N matches: date/season/match/event/score/pts/perf
    - Summary: 2 columns (last N | overall) incl. Trend (-3..+3) with arrows
    - Donations: 1 header + 1 data line
    """

    DONATION_START_DATE = "2025-11-01"

    player_meta = stats_repo.get_player_stats_meta(player_id)
    if not player_meta:
        print(f"⚠️ No player with id {player_id}.")
        return

    total_matches_overall = stats_repo.count_player_matchscores(player_id)
    total_unexcused_overall = stats_repo.count_player_unexcused_absences(player_id)

    last_matches = stats_repo.fetch_player_last_matches(player_id, last_n)
    if not last_matches:
        print(f"⚠️ No matches found for player {player_id}.")
        return

    overall_matches = stats_repo.fetch_player_overall_matches(player_id)
    overall_match_ids = [m[0] for m in overall_matches]
    median_rows = stats_repo.fetch_match_rows_for_medians(overall_match_ids)
    med_by_match = stats_service.calculate_match_medians(median_rows)
    summary = stats_service.summarize_player_stats(
        last_matches,
        overall_matches,
        med_by_match,
        total_unexcused_overall=total_unexcused_overall,
    )

    cutoff_date = stats_repo.get_latest_donation_date()
    donation_matches = (
        stats_repo.count_player_donation_matches(player_id, DONATION_START_DATE, cutoff_date)
        if cutoff_date is not None
        else 0
    )
    donation_total = (
        stats_repo.get_player_latest_donation_total(player_id, cutoff_date)
        if cutoff_date is not None
        else 0
    )
    donations = stats_service.summarize_player_donations(
        start_date=DONATION_START_DATE,
        cutoff_date=cutoff_date,
        matches=donation_matches,
        total=donation_total,
    )

    stats_output.print_player_detail(
        player_id=player_id,
        player_meta=player_meta,
        last_n=last_n,
        last_matches=last_matches,
        summary=summary,
        total_matches_overall=total_matches_overall,
        donations=donations,
    )
