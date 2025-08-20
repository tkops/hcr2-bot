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
    elif cmd == "scatter":
        n = int(args[0]) if args else 20
        show_season_score_scatter(last_n=n, height=12, symbol="🔵")
    else:
        print(f"❌ Unknown stats command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py stats <command> [args]")
    print("\nAvailable commands:")
    print("  avg [season]              Show player averages for current or given season")
    print("  alias                     Show alias of active players in plte team sorted by rank")
    print("  rank [season]             Rank ALL active PLTE players (no one skipped; no-score at bottom)")
    print("  scatter [N]               Avergage Score Plot for last N seasons)")

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

def _fetch_avg_score_last_seasons(cur, last_n=20):
    """
    Liefert [(season_number, avg_score_scaled), ...] für die letzten N Seasons.
    score wird auf 4 Tracks skaliert (wie üblich): score * 4 / tracks
    Es werden nur aktive PLTE-Spieler berücksichtigt.
    """
    cur.execute("""
        SELECT m.season_number,
               AVG( ms.score * 4.0 / NULLIF(t.tracks, 0) ) AS avg_scaled
        FROM matchscore ms
        JOIN match m       ON m.id = ms.match_id
        JOIN teamevent t   ON t.id = m.teamevent_id
        JOIN players p     ON p.id = ms.player_id
        WHERE ms.score IS NOT NULL
          AND p.team = 'PLTE'
          AND p.active = 1
        GROUP BY m.season_number
        ORDER BY m.season_number DESC
        LIMIT ?
    """, (last_n,))
    rows = cur.fetchall()  # [(season, avg)]
    # Für Plot: älteste→neueste (links→rechts)
    rows.reverse()
    return rows


def _format_k(v):
    return f"{int(round(v/1000.0))}k"

def _scatter_fixed(rows, width=70, height=35, x_labels=6, symbol=None,
                   title="Avg score per season (scaled)"):
    """
    rows: [(season_number, avg_score), ...]  (aufsteigend nach Season!)
    width:  Gesamtbreite inkl. Y-Achse/Labels
    height: Plot-Höhe (Zeilen)
    x_labels: Anzahl X-Achsenlabels (z.B. 6) – gleichmäßig verteilt
    """
    if not rows:
        return "```No data.```"
    #symbol = "●"
    symbol = "."

    # --- Helpers ---
    def _format_k(v: float) -> str:
        return f"{int(round(v/1000.0))}k"

    seasons = [int(s) for s, _ in rows]
    vals    = [float(v) for _, v in rows]
    n = len(seasons)

    vmin, vmax = min(vals), max(vals)
    if vmax == vmin:
        vmax = vmin + 1.0

    # Fester linker Rand (Y-Label + ' │ ') = 9 Zeichen
    gutter = 9
    plot_cols = max(10, width - gutter)  # Plotbreite
    # Spaltenindex 0..plot_cols-1 gleichmäßig über alle Seasons mappen
    col_idx = [0] * n
    if n == 1:
        col_idx[0] = plot_cols - 1  # rechts
    else:
        for i in range(n):
            col_idx[i] = round(i * (plot_cols - 1) / (n - 1))

    # Werte → Y-Level (0..height-1), unten=0
    def to_level(v: float) -> int:
        r = (v - vmin) / (vmax - vmin)
        return int(round(r * (height - 1)))
    y_levels = [to_level(v) for v in vals]

    lines = [f"{title} (min={int(vmin)}, max={int(vmax)})"]

    # Plotzeilen (top → bottom)
    for h in range(height - 1, -1, -1):
        # Y-Labels: oben / Mitte / unten in k
        if h in {height - 1, (height - 1) // 2, 0}:
            y_val = vmin + (vmax - vmin) * (h / (height - 1))
            ylab = _format_k(y_val).rjust(6)
            left = f"{ylab} │ "
        else:
            left = " " * (gutter - 2) + "│ "

        row = [" "] * plot_cols
        for ci, yl in zip(col_idx, y_levels):
            if yl == h and 0 <= ci < plot_cols:
                row[ci] = symbol
        lines.append(left + "".join(row))

    # X-Achse
    lines.append(" " * (gutter - 2) + "└" + "─" * plot_cols)

    # X-Labels: exakt x_labels Positionen gleichmäßig über Plotbreite
    if x_labels < 2:
        x_labels = 2
    # Zielspalten (gleichmäßiger Abstand, inkl. links/rechts)
    label_positions = [round(j * (plot_cols - 1) / (x_labels - 1)) for j in range(x_labels)]
    # Zu druckende Seasons (gleichmäßig über Index 0..n-1, inkl. erste/letzte)
    label_indices   = [round(j * (n - 1) / (x_labels - 1)) for j in range(x_labels)]

    lbl_buf = [" "] * plot_cols
    for pos, idx in zip(label_positions, label_indices):
        lab = f"S{seasons[idx]}"
        start = min(max(0, pos - len(lab)//2), max(0, plot_cols - len(lab)))
        for k, ch in enumerate(lab):
            p = start + k
            if 0 <= p < plot_cols:
                lbl_buf[p] = ch

    lines.append(" " * gutter + "".join(lbl_buf).rstrip())
    return "```\n" + "\n".join(lines) + "\n```"



def show_season_score_scatter(last_n=20, height=35, width=70, x_labels=6, symbol="."):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        rows = _fetch_avg_score_last_seasons(cur, last_n=last_n)  # wie zuvor
        if not rows:
            print("⚠️ No data.")
            return
        print(_scatter_fixed(rows, width=width, height=height, x_labels=x_labels, symbol=symbol))



