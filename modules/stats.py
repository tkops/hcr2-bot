import sqlite3
import statistics
import datetime

DB_PATH = "db/hcr2.db"

def handle_command(cmd, args):
    if cmd == "avg":
        season_arg = int(args[0]) if args else None
        show_average(season_arg)
    elif cmd == "alias":
        show_plte_alias()
    elif cmd == "rank":
        season_arg = int(args[0]) if args else None
        rank_active_plte(season_arg)
    else:
        print(f"❌ Unknown stats command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py stats <command> [args]")
    print("\nAvailable commands:")
    print("  avg [season]              Show player averages for current or given season")
    print("  alias                     Show alias of active players in plte team sorted by rank")
    print("  rank [season]             Rank ALL active PLTE players (no one skipped; no-score at bottom)")

def format_k(value):
    if value is None:
        return "-"
    abs_val = abs(value)
    if abs_val >= 100:
        return f"{'-' if value < 0 else ''}{round(abs_val / 1000, 1)}k"
    else:
        return f"{'-' if value < 0 else ''}0.0k"

def find_current_season(cur):
    today = datetime.date.today().isoformat()
    cur.execute("SELECT number FROM season WHERE start <= ? ORDER BY start DESC LIMIT 1", (today,))
    row = cur.fetchone()
    return row[0] if row else None

def _fetch_season_rows(cur, season_number):
    cur.execute("""
        SELECT
            ms.player_id,
            p.name,
            p.alias,
            p.team,
            p.active,
            ms.score,
            m.id,
            t.tracks,
            t.max_score_per_track
        FROM matchscore ms
        JOIN players p ON ms.player_id = p.id
        JOIN match m ON ms.match_id = m.id
        JOIN teamevent t ON m.teamevent_id = t.id
        WHERE m.season_number = ?
    """, (season_number,))
    return cur.fetchall()

def show_average(season_number=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if season_number is None:
            season_number = find_current_season(cur)

        if not season_number:
            print("⚠️ No matching season found.")
            return

        rows = _fetch_season_rows(cur, season_number)
        if not rows:
            print("⚠️ No match scores found.")
            return

        scores_by_match = {}
        for pid, name, alias, team, active, score, match_id, tracks, max_score in rows:
            if score is None:
                continue
            scaled_score = score * 4 / tracks if tracks else score
            scores_by_match.setdefault(match_id, []).append((pid, name, scaled_score))

        player_scores = {}
        player_names = {}
        player_counts = {}

        for match_id, entries in scores_by_match.items():
            scores = [score for _, _, score in entries]
            if not scores:
                continue
            try:
                median = statistics.median(scores)
            except statistics.StatisticsError:
                continue
            for pid, name, score in entries:
                delta = score - median
                player_scores.setdefault(pid, []).append(delta)
                player_names[pid] = name
                player_counts[pid] = player_counts.get(pid, 0) + 1

        cur.execute("SELECT COUNT(*) FROM match WHERE season_number = ?", (season_number,))
        total_matches = cur.fetchone()[0]
        min_matches = round(total_matches * 0.8)

        entries = []
        for pid, deltas in player_scores.items():
            count = player_counts.get(pid, 0)
            if count < min_matches:
                continue
            avg_delta = round(sum(deltas) / len(deltas))
            entries.append((player_names[pid], avg_delta, count))

        print(f"{'#':>2}   {'Lady':<14} {'Perf':>6} {'Mat.':<2}")
        print("-" * 31)

        for i, (name, delta, count) in enumerate(sorted(entries, key=lambda x: x[1], reverse=True), 1):
            if i > 50:
                break
            print(f"{i:>2}.  {name:<14} {format_k(delta):>6} {count:>2}")

def show_plte_alias():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        season_number = find_current_season(cur)
        if not season_number:
            return

        rows = _fetch_season_rows(cur, season_number)
        if not rows:
            return

        scores_by_match = {}
        for pid, name, alias, team, active, score, match_id, tracks, max_score in rows:
            if score is None or team != "PLTE":
                continue
            scaled_score = score * 4 / tracks if tracks else score
            scores_by_match.setdefault(match_id, []).append((pid, alias, scaled_score))

        player_scores = {}
        player_alias = {}
        player_counts = {}

        for match_id, entries in scores_by_match.items():
            scores = [score for _, _, score in entries]
            if not scores:
                continue
            try:
                median = statistics.median(scores)
            except statistics.StatisticsError:
                continue
            for pid, alias, score in entries:
                delta = score - median
                player_scores.setdefault(pid, []).append(delta)
                player_alias[pid] = alias
                player_counts[pid] = player_counts.get(pid, 0) + 1

        cur.execute("SELECT id FROM players WHERE active = 1 AND team = 'PLTE'")
        active_ids = {row[0] for row in cur.fetchall()}

        entries = []
        for pid, deltas in player_scores.items():
            if pid not in active_ids:
                continue
            avg_delta = round(sum(deltas) / len(deltas))
            entries.append((player_alias[pid], avg_delta))

        for alias, _ in sorted(entries, key=lambda x: x[1], reverse=True):
            print(alias)

def rank_active_plte(season_number=None):
    """
    Rank ALL active PLTE players:
    - Uses avg delta vs. median per match (scaled to 4 tracks) like `avg`
    - No 80% participation filter
    - Players without any score are listed at the bottom
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if season_number is None:
            season_number = find_current_season(cur)

        if not season_number:
            print("⚠️ No matching season found.")
            return

        # Base set: all active PLTE players (id -> name)
        cur.execute("SELECT id, name FROM players WHERE active = 1 AND team = 'PLTE'")
        active_players = cur.fetchall()
        if not active_players:
            print("⚠️ No active PLTE players.")
            return
        id_to_name = {pid: name for pid, name in active_players}

        # Pull all season rows
        rows = _fetch_season_rows(cur, season_number)

        # Build per-match lists limited to PLTE active players
        scores_by_match = {}
        for pid, name, alias, team, active, score, match_id, tracks, max_score in rows:
            if team != "PLTE" or not active:
                continue
            if score is None:
                continue
            scaled_score = score * 4 / tracks if tracks else score
            scores_by_match.setdefault(match_id, []).append((pid, name, scaled_score))

        # Compute deltas vs. median for each match
        player_scores = {}
        player_counts = {}

        for match_id, entries in scores_by_match.items():
            scores = [score for _, _, score in entries]
            if not scores:
                continue
            try:
                median = statistics.median(scores)
            except statistics.StatisticsError:
                continue
            for pid, name, score in entries:
                delta = score - median
                player_scores.setdefault(pid, []).append(delta)
                player_counts[pid] = player_counts.get(pid, 0) + 1

        # Build final list: include ALL active PLTE players
        with_scores = []
        without_scores = []
        for pid, name in id_to_name.items():
            deltas = player_scores.get(pid)
            if deltas:
                avg_delta = round(sum(deltas) / len(deltas))
                count = player_counts.get(pid, 0)
                with_scores.append((name, avg_delta, count))
            else:
                # No scores this season
                without_scores.append((name, None, 0))

        # Sort: with scores by avg_delta desc; without scores alphabetically
        with_scores_sorted = sorted(with_scores, key=lambda x: x[1], reverse=True)
        without_scores_sorted = sorted(without_scores, key=lambda x: x[0].lower())

        entries = with_scores_sorted + without_scores_sorted

        # Print
        print(f"{'#':>2}   {'Lady':<14} {'Perf':>6} {'Mat.':<2}")
        print("-" * 31)
        for i, (name, delta, count) in enumerate(entries, 1):
            print(f"{i:>2}.  {name:<14} {format_k(delta):>6} {count:>2}")

