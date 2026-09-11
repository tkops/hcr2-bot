#!/usr/bin/env python3
from typing import Callable, Optional

from hcr2.output import broom as broom_output
from hcr2.output import stats as stats_output
from hcr2.repositories import stats as stats_repo
from hcr2.services import broom as broom_service
from hcr2.services import stats as stats_service
from modules.common import (
    get_arg_value,
    is_help_request,
    parse_int,
    print_command_help,
    print_unknown_command,
)

PERF_TABLE_LIMIT = 50

# ---------------------------------------------------------------------------

def handle_command(cmd, args):
    if is_help_request(cmd, *args):
        print_help()
        return

    handlers: dict[str, Callable[[list[str]], None]] = {
        "alias": _handle_alias,
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
        "broom": _handle_broom,
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



def _handle_alias(args):
    if args:
        print("Usage: stats alias")
        return
    show_plte_alias()



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

USAGE_BROOM = (
    "Usage: stats broom [--season <n>] [--last <matches>] [--top <n>] [--all] "
    "[--include-leaders] [--json]"
)


def _handle_broom(args):
    window = None            # None = die Saison ist das Fenster
    season = None            # None = die aktuelle Saison
    limit = None             # None = so viele wie Plätze frei werden sollen

    raw_window = get_arg_value(args, "--last")
    if raw_window is not None:
        window = parse_int(raw_window, default=None)
        if window is None or window < 1:
            print(USAGE_BROOM)
            return

    raw_season = get_arg_value(args, "--season")
    if raw_season is not None:
        season = parse_int(raw_season, default=None)
        if season is None or season < 1:
            print(USAGE_BROOM)
            return
        # Zwei Zeiträume in einem Aufruf: einer von beiden würde still gewinnen, und
        # welcher, stünde nur im Kopf der Ausgabe.
        if window is not None:
            print("❌ --season und --last schließen sich aus.")
            print(USAGE_BROOM)
            return

    raw_limit = get_arg_value(args, "--top")
    if raw_limit is not None:
        limit = parse_int(raw_limit, default=None)
        if limit is None or limit < 1:
            print(USAGE_BROOM)
            return

    result = broom_service.rank(
        season=season,
        window=window,
        include_leaders="--include-leaders" in args,
    )
    if "--json" in args:
        broom_output.print_json(result)
        return
    broom_output.print_result(result, limit=limit, show_all="--all" in args)


def print_help():
    print_command_help(
        usage="hcr2.py stats <command> [options]",
        commands=[
            (
                "perf [season] [--inactive] [--no-skip] [--driven-only]",
                "Show performance ranking",
            ),
            ("alias", "Show aliases of active PLTE players sorted by rank"),
            ("te <teamevent_id>", "Show rank stats for one team event"),
            ("te-user [n]", "Show relative team-event stats: 0=current, 1=last, 2=previous"),
            ("scatter [N]", "Show average score plot for the last N seasons"),
            ("bdayplot", "Show birthday plot"),
            ("battle <id1> <id2> [season]", "Compare season stats"),
            ("absent [season]", "Show absent stats"),
            ("player <id> [N]", "Show the last matches for one player"),
            ("score [season] [--skip|--no-skip]", "Show sum of scores per player in season"),
            ("points [season] [--skip|--no-skip]", "Show sum of points per player in season"),
            (
                "broom [--season <n>] [--last <matches>] [--top <n>] [--all] "
                "[--include-leaders] [--json]",
                "Rank candidates for removal, with reasons (German output)",
            ),
        ],
        options=[
            (
                "--inactive",
                "perf: add everyone else with a row in that season, members who have\n"
                "since left included - the only way an old season stays readable,\n"
                "since the field back then is what the median came from. Brings the\n"
                "20% minimum with it, because the one-match entries it filters all\n"
                "come from that group. Without it the list is today's PLTE roster.",
            ),
            (
                "--no-skip",
                "perf/score/points: also list members who have no score in that\n"
                "season at all, with '-' at the bottom. The base is TODAY's roster,\n"
                "not the season, so it rules out --inactive. Skipped is the PLAYER\n"
                "in the list, never a match in the calculation.",
            ),
            (
                "--driven-only",
                "perf: stop counting unexcused absence as a zero score. Counting it\n"
                "is the default on purpose - not showing up is meant to hurt the\n"
                "figure. This answers the other question: how does she drive when\n"
                "she drives. broom always measures it this way.",
            ),
        ],
        notes=[
            "score and points default to scored active PLTE players.",
            "broom looks at the current season, skips leaders, and needs at least",
            f"{broom_service.MIN_MATCHES} driven matches per player for the yardstick "
            "cohort.",
            f"--last <matches> replaces the season with a fixed window "
            f"(was {broom_service.WINDOW_MATCHES}).",
        ],
    )

# ---------------------------------------------------------------------------

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

def show_average(season_number=None, include_inactive=False, list_all=False, driven_only=False):
    """
    Default:
      - only currently active PLTE players, every one of them with >0 scored matches.
        This is what a running season is asked about, and it is what the bot shows.

    --inactive:
      - adds everyone else who has a row in that season, members who have since left
        included - the only way an old season stays readable, because the field back
        then is what the median was built from. Brings the 20% minimum with it: the
        one-match entries that need filtering all come from this group.

    --no-skip (list_all):
      - fills the list up with today's PLTE players who have no scored match in that
        season, shown with "-" at the bottom. The base is the *current* roster, so it
        rules out --inactive: former members with a score and newcomers without one
        would otherwise share one table.

    --driven-only:
      - unexcused absence stops counting as a zero score. The default deliberately
        counts it, because not showing up is meant to hurt the performance figure;
        this flag answers the other question: how does she drive when she drives.
    """
    if list_all:
        include_inactive = False
    active_only = not include_inactive
    if season_number is None:
        season_number = find_current_season(None)
    if not season_number:
        stats_output.print_no_matching_season()
        return

    s_name, s_div = _get_season_meta(None, season_number)
    stats_output.print_perf_header(season_number, s_name, s_div)

    # Die 20%-Hürde gehört zu --inactive: die Ein-Match-Einträge, gegen die sie gebaut
    # ist, kommen aus der Gruppe der Ausgetretenen. Im Kadermodus zählt jede mit einem
    # gefahrenen Match, denn wer im Team ist, gehört in die Liste.
    if include_inactive:
        total_matches, min_matches = _get_min_required_matches(None, season_number, ratio=0.20)
        stats_output.print_required_matches(total_matches, min_matches)
    else:
        total_matches = 0
        min_matches = 1

    rows = _fetch_season_rows(None, season_number)
    if not rows:
        stats_output.print_no_match_scores()
        return

    # Scores grouped by match.
    scores_by_match = {}
    for pid, name, alias, team, active, score, points, absent, match_id, tracks, max_score in rows:
        if score is None or _is_absent(score, points, absent):
            continue

        # --driven-only: nur tatsächlich gefahrene Matches. Ohne das Flag bleibt eine
        # unentschuldigte Null im Schnitt - sie ist dort ausdrücklich eine Strafe.
        if driven_only and score <= 0:
            continue

        # Limit to current active PLTE players only for --active.
        if active_only and not _is_active_plte(active, team):
            continue

        _append_scored_match(scores_by_match, match_id, pid, name, score, tracks)

    if not scores_by_match:
        stats_output.print_no_match_scores()
        return

    player_scores, player_names, player_counts = _calculate_match_deltas(scores_by_match)
    entries = _build_delta_entries(player_scores, player_names, player_counts, min_matches)

    if not entries and not list_all:
        stats_output.print_no_perf_entries(active_only=active_only, min_matches=min_matches)
        return

    if list_all:
        entries = _append_players_without_scores(entries, player_scores)
        # Direkt an die Ausgabe, nicht über _print_perf_table: das sortiert erneut und
        # stolpert über die "-"-Zeilen, die keinen Wert haben. Die Reihenfolge steht
        # hier schon - Gewertete nach Leistung, der Rest alphabetisch dahinter.
        # Kein Limit: abzuschneiden hieße, genau die wegzulassen, für die das Flag da ist.
        stats_output.print_perf_table(entries, limit=None)
        return

    _print_perf_table(entries, limit=PERF_TABLE_LIMIT)


def _append_players_without_scores(entries, player_scores):
    """Aktive PLTE-Spielerinnen ohne Wertung in der Saison, alphabetisch ans Ende.

    Grundmenge ist der *heutige* Kader, nicht die Saison - das Flag beantwortet
    "wer aus dem Team fehlt hier", nicht "wer war damals dabei".
    """
    listed = {name for name, _, _ in entries}
    without = [
        (name, None, 0)
        for pid, name in stats_repo.list_active_plte_players()
        if pid not in player_scores and name not in listed
    ]
    without.sort(key=lambda entry: entry[0].lower())
    return _sorted_delta_entries(entries) + without

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

    stats_output.print_aliases([alias for alias, _ in sorted(entries, key=lambda x: x[1], reverse=True)])

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Wrapper: stats perf
# ---------------------------------------------------------------------------

USAGE_PERF = "Usage: stats perf [season] [--inactive] [--no-skip] [--driven-only]"


def show_perf(args):
    """
    stats perf [season] [--inactive] [--no-skip] [--driven-only]

    default:
      - all players with at least 20% matches in the season
      - regardless of current active/team status

    --active:
      - only currently active PLTE players
      - all with >0 matches
    """
    season_number = None
    include_inactive = False
    list_all = False
    driven_only = False

    for a in args:
        if a == "--inactive":
            include_inactive = True
        elif a == "--active":
            # War bis 1.13.1 nötig und ist jetzt der Default - weiter angenommen,
            # damit ein getipptes Kommando nicht mit einer Usage-Zeile antwortet.
            include_inactive = False
        elif a == "--no-skip":
            list_all = True
        elif a == "--skip":
            list_all = False
        elif a == "--driven-only":
            driven_only = True
        else:
            try:
                season_number = int(a)
            except ValueError:
                print(USAGE_PERF)
                return

    show_average(
        season_number,
        include_inactive=include_inactive,
        list_all=list_all,
        driven_only=driven_only,
    )

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
        stats_output.print_no_matching_season()
        return

    # Header metadata.
    s_name, s_div = _get_season_meta(None, season_number)
    stats_output.print_sum_metric_header(metric, season_number, s_name, s_div)

    # Active PLTE players for name lookup and the no-skip list.
    active_players = stats_repo.list_active_plte_players()
    if not active_players:
        stats_output.print_no_active_plte_players()
        return
    id_to_name = {pid: name for pid, name in active_players}

    rows = _fetch_season_rows(None, season_number)
    if not rows:
        stats_output.print_no_match_scores()
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

def _scatter_fixed(rows, width=70, height=35, x_labels=6, symbol=None,
                   title="Avg score per season (scaled)"):
    return stats_output.scatter_fixed(rows, width=width, height=height, x_labels=x_labels, symbol=symbol, title=title)

def show_season_score_scatter(last_n=20, height=35, width=70, x_labels=6, symbol="."):
    rows = _fetch_avg_score_last_seasons(None, last_n=last_n)
    if not rows:
        stats_output.print_no_data()
        return
    stats_output.print_scatter_plot(_scatter_fixed(rows, width=width, height=height, x_labels=x_labels, symbol=symbol))

# ---------------------------------------------------------------------------

def show_birthday_plot(width=77, height=31, cols_per_month=2, cell_w=2):
    """
    31 rows (days 1..31, top=31). 12 months, each with 3 cells of 2 columns.
    Uses the exact emoji from players.emoji.
    """
    stats_output.print_birthday_plot(
        stats_output.birthday_plot(
            stats_repo.fetch_birthday_plot_rows(),
            width=width,
            height=height,
            cols_per_month=cols_per_month,
            cell_w=cell_w,
        )
    )

# ---------------------------------------------------------------------------

def show_battle(player1_id, player2_id, season_number=None, height=30, max_matches=15, col_width=3):
    """
    Battle plot for two players in one season.
    Absent players are not plotted.
    """
    if season_number is None:
        season_number = find_current_season(None)
        if not season_number:
            stats_output.print_no_season()
            return

    matches = stats_repo.fetch_season_matches(season_number)
    if not matches:
        stats_output.print_no_matches_found()
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
        stats_output.print_no_matching_season()
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
        stats_output.print_no_teamevent_for_offset(offset)
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
        stats_output.print_no_teamevent(te_id)
        return

    te_name, iso_year, iso_week, te_tracks, te_max = row

    # Fetch all matches for this team event, including scores.
    rows = stats_repo.fetch_teamevent_rows(te_id)

    if not rows:
        stats_output.print_no_teamevent_scores(te_id)
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
        stats_output.print_no_valid_teamevent_scores(te_id)
        return

    # Deltas vs. median per match.
    player_scores, player_names, player_counts = _calculate_match_deltas(scores_by_match)

    if not player_scores:
        stats_output.print_no_teamevent_rank_data(te_id)
        return

    # Build result entries.
    entries = _build_delta_entries(player_scores, player_names, player_counts)

    stats_output.print_teamevent_perf_header(te_id, te_name, iso_year, iso_week)
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
        stats_output.print_no_player(player_id)
        return

    total_matches_overall = stats_repo.count_player_matchscores(player_id)
    total_unexcused_overall = stats_repo.count_player_unexcused_absences(player_id)

    last_matches = stats_repo.fetch_player_last_matches(player_id, last_n)
    if not last_matches:
        stats_output.print_no_player_matches(player_id)
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
