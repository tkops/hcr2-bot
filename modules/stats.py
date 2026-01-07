
#!/usr/bin/env python3
import sqlite3
import statistics
import datetime
import re

DB_PATH = "../hcr2-db/hcr2.db"
BIRTHDAY_RE = re.compile(r"^\s*(\d{1,2})\D+(\d{1,2})\s*$")  # z. B. 08-18, 7/3, 07.03.

# ---------------------------------------------------------------------------

def handle_command(cmd, args):
    if cmd == "avg":
        season_arg = int(args[0]) if args else None
        show_average(season_arg)
    elif cmd == "alias":
        show_plte_alias()
    elif cmd == "rank":
        season_arg = int(args[0]) if args else None
        rank_active_plte(season_arg)
    elif cmd == "perf":
        show_perf(args)
    elif cmd == "scatter":
        n = int(args[0]) if args else 20
        show_season_score_scatter(last_n=n, height=12, symbol="🔵")
    elif cmd == "bdayplot":
        show_birthday_plot(width=32, height=31, cols_per_month=1)
    elif cmd == "battle":
        if len(args) < 2:
            print("Usage: stats battle <id1> <id2> [season]")
            return
        id1 = int(args[0])
        id2 = int(args[1])
        season = int(args[2]) if len(args) > 2 else None
        show_battle(id1, id2, season)
    elif cmd == "absent":
        season_arg = int(args[0]) if args else None
        show_absent(season_arg)
    elif cmd == "te":
        if not args:
            print("Usage: stats te <teamevent_id>")
            return
        te_id = int(args[0])
        show_teamevent_stats(te_id)
    elif cmd == "te-user":
        # te-user       -> aktuelles/letztes Teamevent (Offset 0)
        # te-user 1     -> davor
        # te-user 2     -> vorletztes, usw.
        offset = int(args[0]) if args else 0
        show_teamevent_stats_user(offset)
    elif cmd == "score":
        show_score(args)
    elif cmd == "points":
        show_points(args)
    elif cmd == "player":
        if not args:
            print("Usage: stats player <player_id> [N]")
            return
        player_id = int(args[0])
        n = int(args[1]) if len(args) > 1 else 15
        show_player_last_matches(player_id, last_n=n)
    else:
        print(f"❌ Unknown stats command: {cmd}")
        print_help()

def print_help():
    print("Usage: python hcr2.py stats <command> [args]")
    print("\nAvailable commands:")
    print("  perf [season] [--skip|--no-skip]")
    print("                           Performance ranking:")
    print("                           default / --skip    → like avg (nur gewertete Spieler)")
    print("                           --no-skip           → like rank (alle aktiven PLTE)")
    print("  avg [season]              (legacy) Show player averages for current or given season")
    print("  alias                     Show alias of active players in plte team sorted by rank")
    print("  rank [season]             (legacy) Rank ALL active PLTE players (no one skipped; no-score at bottom)")
    print("  te <te-id>                Rank stats for given team event")
    print("  te-user [n]               Like 'te' but with relative index: 0=current, 1=last, 2=prev, ...")
    print("  scatter [N]               Avergage Score Plot for last N seasons")
    print("  bdayplot                  Birthday Plot")
    print("  battle <id> <id> [s]      Seasonstat Compair")
    print("  absent [season]           Absent stats")
    print("  player <id>               Show player stats")
    print("  score [season] [--skip|--no-skip]")
    print("                           Summe der Scores je Spieler in Season (default nur gewertete aktive PLTE)")
    print("  points [season] [--skip|--no-skip]")
    print("                           Summe der Points je Spieler in Season (default nur gewertete aktive PLTE)")

# ---------------------------------------------------------------------------

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

def _get_season_meta(cur, season_number):
    """
    Liefert (name, division) für die Season.
    Falls Spalten nicht existieren, werden leere Strings zurückgegeben.
    """
    name = ""
    division = ""
    try:
        cur.execute("SELECT name, division FROM season WHERE number = ?", (season_number,))
        row = cur.fetchone()
        if row:
            name = row[0] or ""
            division = row[1] or ""
    except sqlite3.OperationalError:
        pass
    return name, division

def _fetch_season_rows(cur, season_number):
    """
    Holt alle relevanten Zeilen der Season inkl. points und absent.
    """
    cur.execute("""
        SELECT
            ms.player_id,
            p.name,
            p.alias,
            p.team,
            p.active,
            ms.score,
            ms.points,
            ms.absent,
            m.id,
            t.tracks,
            t.max_score_per_track
        FROM matchscore ms
        JOIN players   p ON ms.player_id = p.id
        JOIN match     m ON ms.match_id = m.id
        JOIN teamevent t ON m.teamevent_id = t.id
        WHERE m.season_number = ?
    """, (season_number,))
    return cur.fetchall()


def _is_absent(score, points, absent_flag):
    # Hat jemand >0 Punkte/Score, zählt er als teilgenommen – auch wenn absent=1 gesetzt ist.
    if score is not None and score > 0:
        return False
    # Fallback, falls absent nicht gepflegt ist: points==0 und score==0/None ⇒ absent
    if absent_flag is not None:
        return bool(absent_flag) and (score is None or score == 0)
    return (points is not None and points == 0) and (score is None or score == 0)


# ---------------------------------------------------------------------------

def show_average(season_number=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if season_number is None:
            season_number = find_current_season(cur)
        if not season_number:
            print("⚠️ No matching season found.")
            return

        # Header
        s_name, s_div = _get_season_meta(cur, season_number)
        header_line = f"📈Performance Season {season_number} ({s_name}) DIV: {s_div}".rstrip()
        print(header_line)

        rows = _fetch_season_rows(cur, season_number)
        if not rows:
            print("⚠️ No match scores found.")
            return

        # Matchweise Scores, Abwesende ignorieren
        scores_by_match = {}
        for pid, name, alias, team, active, score, points, absent, match_id, tracks, max_score in rows:
            # nur aktive PLTE
            if not active:
                continue
            if not team or team.upper() != "PLTE":
                continue

            if score is None or _is_absent(score, points, absent):
                continue

            scaled_score = score * 4 / tracks if tracks else score
            scores_by_match.setdefault(match_id, []).append((pid, name, scaled_score))

        if not scores_by_match:
            print("⚠️ No match scores found.")
            return

        # Deltas vs. Median
        player_scores = {}
        player_names = {}
        player_counts = {}

        for match_id, entries in scores_by_match.items():
            scores = [s for _, _, s in entries]
            if not scores:
                continue
            try:
                median = statistics.median(scores)
            except statistics.StatisticsError:
                continue
            for pid, name, s in entries:
                delta = s - median
                player_scores.setdefault(pid, []).append(delta)
                player_names[pid] = name
                player_counts[pid] = player_counts.get(pid, 0) + 1

        # Mindestteilnahme auf Basis tatsächlich gewerteter Matches
        total_matches = len(scores_by_match)
        min_matches = 1  # ggf. auf max(1, round(total_matches*0.8)) ändern

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

# ---------------------------------------------------------------------------

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
        for pid, name, alias, team, active, score, points, absent, match_id, tracks, max_score in rows:
            if team != "PLTE" or score is None or _is_absent(score, points, absent):
                continue
            scaled_score = score * 4 / tracks if tracks else score
            scores_by_match.setdefault(match_id, []).append((pid, alias, scaled_score))

        player_scores = {}
        player_alias = {}
        player_counts = {}

        for match_id, entries in scores_by_match.items():
            scores = [s for _, _, s in entries]
            if not scores:
                continue
            try:
                median = statistics.median(scores)
            except statistics.StatisticsError:
                continue
            for pid, alias, s in entries:
                delta = s - median
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

# ---------------------------------------------------------------------------

def rank_active_plte(season_number=None):
    """
    Rank ALL active PLTE players:
    - Avg delta vs. Median per Match (scaled to 4 tracks) wie `avg`
    - Kein 80%-Filter
    - Spieler ohne Score am Ende
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if season_number is None:
            season_number = find_current_season(cur)
        if not season_number:
            print("⚠️ No matching season found.")
            return

        # Alle aktiven PLTE
        cur.execute("SELECT id, name FROM players WHERE active = 1 AND team = 'PLTE'")
        active_players = cur.fetchall()
        if not active_players:
            print("⚠️ No active PLTE players.")
            return
        id_to_name = {pid: name for pid, name in active_players}

        rows = _fetch_season_rows(cur, season_number)

        scores_by_match = {}
        for pid, name, alias, team, active, score, points, absent, match_id, tracks, max_score in rows:
            if team != "PLTE" or not active:
                continue
            if score is None or _is_absent(score, points, absent):
                continue
            scaled_score = score * 4 / tracks if tracks else score
            scores_by_match.setdefault(match_id, []).append((pid, name, scaled_score))

        player_scores = {}
        player_counts = {}

        for match_id, entries in scores_by_match.items():
            scores = [s for _, _, s in entries]
            if not scores:
                continue
            try:
                median = statistics.median(scores)
            except statistics.StatisticsError:
                continue
            for pid, name, s in entries:
                delta = s - median
                player_scores.setdefault(pid, []).append(delta)
                player_counts[pid] = player_counts.get(pid, 0) + 1

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
        print("-" * 31)
        for i, (name, delta, count) in enumerate(entries, 1):
            print(f"{i:>2}.  {name:<14} {format_k(delta):>6} {count:>2}")

# ---------------------------------------------------------------------------
# Neuer Wrapper: stats perf
# ---------------------------------------------------------------------------

def show_perf(args):
    """
    stats perf [season] [--skip|--no-skip]
      --skip / default   → show_average (aktuelle Logik)
      --no-skip          → rank_active_plte (alle aktiven PLTE, No-Score unten)
    """
    season_number = None
    skip = True  # default

    for a in args:
        if a == "--no-skip":
            skip = False
        elif a == "--skip":
            skip = True
        else:
            # Versuch, Season zu parsen
            try:
                season_number = int(a)
            except ValueError:
                print("Usage: stats perf [season] [--skip|--no-skip]")
                return

    if skip:
        show_average(season_number)
    else:
        rank_active_plte(season_number)

# ---------------------------------------------------------------------------
# Neuer Wrapper: stats score / stats points
# ---------------------------------------------------------------------------

def show_score(args):
    """
    stats score [season] [--skip|--no-skip]
      --skip / default   → nur aktive PLTE mit gewerteter Teilnahme (nicht abwesend), Summe der Scores
      --no-skip          → alle aktiven PLTE, No-Score unten
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
      --skip / default   → nur aktive PLTE mit gewerteter Teilnahme (nicht abwesend), Summe der Points
      --no-skip          → alle aktiven PLTE, No-Points unten
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
    Aggregiert und rankt Summen pro Spieler für eine Season.
    metric: "score" oder "points"
    skip=True  : nur aktive PLTE mit gewerteter Teilnahme (nicht abwesend)
    skip=False : alle aktiven PLTE; Spieler ohne Teilnahme/Metrik unten
    """
    assert metric in {"score", "points"}, "metric muss 'score' oder 'points' sein"

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if season_number is None:
            season_number = find_current_season(cur)
        if not season_number:
            print("⚠️ No matching season found.")
            return

        # Header-Infos
        s_name, s_div = _get_season_meta(cur, season_number)
        title_metric = "Score" if metric == "score" else "Points"
        header_line = f"📊{title_metric} Season {season_number} ({s_name}) DIV: {s_div}".rstrip()
        print(header_line)

        # Aktive PLTE (für Namensauflösung und no-skip Liste)
        cur.execute("SELECT id, name FROM players WHERE active = 1 AND UPPER(team) = 'PLTE'")
        active_players = cur.fetchall()
        if not active_players:
            print("⚠️ No active PLTE players.")
            return
        id_to_name = {pid: name for pid, name in active_players}

        rows = _fetch_season_rows(cur, season_number)
        if not rows:
            print("⚠️ No match scores found.")
            return

        totals = {}   # pid -> Summe (score/points)
        counts = {}   # pid -> Anzahl Matches mit gewerteter Teilnahme
        name_by_id = {}  # pid -> Name (Fallback)

        for pid, name, alias, team, active, score, points, absent, match_id, tracks, max_score in rows:
            # Nur PLTE und aktive Spieler berücksichtigen (für beide Modi)
            if not active or not team or team.upper() != "PLTE":
                continue

            # Teilnahme nur zählen, wenn nicht abwesend
            if _is_absent(score, points, absent):
                continue

            # Wert extrahieren
            if metric == "score":
                if score is None:
                    continue  # ohne Score hier nichts aufsummieren
                value = int(score)
            else:  # metric == "points"
                value = int(points or 0)

            totals[pid] = totals.get(pid, 0) + value
            counts[pid] = counts.get(pid, 0) + 1
            name_by_id[pid] = name

        if skip:
            # Nur Spieler mit Teilnahme/Metrik ausgeben, nach Summe sortiert
            entries = []
            for pid, total in totals.items():
                pname = id_to_name.get(pid, name_by_id.get(pid, f"ID {pid}"))
                cnt = counts.get(pid, 0)
                entries.append((pname, total, cnt))

            entries.sort(key=lambda x: x[1], reverse=True)

            # Ausgabe
            col_label = "Score" if metric == "score" else "Pts"
            print(f"{'#':>2}   {'Lady':<14} {col_label:>6} {'Mat.':>2}")
            print("-" * 31)
            for i, (pname, total, cnt) in enumerate(entries, 1):
                print(f"{i:>2}.  {pname:<14} {total:>6} {cnt:>2}")

        else:
            # Alle aktiven PLTE, ohne Werte unten alphabetisch
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

            col_label = "Score" if metric == "score" else "Pts"
            print(f"{'#':>2}   {'Lady':<14} {col_label:>6} {'Mat.':>2}")
            print("-" * 31)
            for i, (pname, total, cnt) in enumerate(entries, 1):
                val_str = f"{total:>6}" if total is not None else f"{'-':>6}"
                print(f"{i:>2}.  {pname:<14} {val_str} {cnt:>2}")

# ---------------------------------------------------------------------------

def _fetch_avg_score_last_seasons(cur, last_n=20):
    cur.execute("""
        SELECT m.season_number,
               AVG( ms.score * 4.0 / NULLIF(t.tracks, 0) ) AS avg_scaled
        FROM matchscore ms
        JOIN match     m ON m.id = ms.match_id
        JOIN teamevent t ON t.id = m.teamevent_id
        JOIN players   p ON p.id = ms.player_id
        WHERE ms.score IS NOT NULL
          AND NOT (IFNULL(ms.absent,0)=1 AND IFNULL(ms.score,0)=0)
          AND p.team = 'PLTE'
          AND p.active = 1
        GROUP BY m.season_number
        ORDER BY m.season_number DESC
        LIMIT ?
    """, (last_n,))
    rows = cur.fetchall()
    rows.reverse()
    return rows


def _format_k(v):
    return f"{int(round(v/1000.0))}k"

def _scatter_fixed(rows, width=70, height=35, x_labels=6, symbol=None,
                   title="Avg score per season (scaled)"):
    if not rows:
        return "```No data.```"
    symbol = "."

    def _format_k(v: float) -> str:
        return f"{int(round(v/1000.0))}k"

    seasons = [int(s) for s, _ in rows]
    vals    = [float(v) for _, v in rows]
    n = len(seasons)

    vmin, vmax = min(vals), max(vals)
    if vmax == vmin:
        vmax = vmin + 1.0

    gutter = 9
    plot_cols = max(10, width - gutter)
    col_idx = [0] * n
    if n == 1:
        col_idx[0] = plot_cols - 1
    else:
        for i in range(n):
            col_idx[i] = round(i * (plot_cols - 1) / (n - 1))

    def to_level(v: float) -> int:
        r = (v - vmin) / (vmax - vmin)
        return int(round(r * (height - 1)))
    y_levels = [to_level(v) for v in vals]

    lines = [f"{title} (min={int(vmin)}, max={int(vmax)})"]

    for h in range(height - 1, -1, -1):
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

    lines.append(" " * (gutter - 2) + "└" + "─" * plot_cols)

    if x_labels < 2:
        x_labels = 2
    label_positions = [round(j * (plot_cols - 1) / (x_labels - 1)) for j in range(x_labels)]
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
        rows = _fetch_avg_score_last_seasons(cur, last_n=last_n)
        if not rows:
            print("⚠️ No data.")
            return
        print(_scatter_fixed(rows, width=width, height=height, x_labels=x_labels, symbol=symbol))

# ---------------------------------------------------------------------------

def show_birthday_plot(width=77, height=31, cols_per_month=2, cell_w=2):
    """
    31 Zeilen (Tage 1..31, oben=31). 12 Monate, je 3 Zellen à 2 Spalten.
    Setzt EXAKT das Emoji aus players.emoji.
    """
    assert height == 31, "height muss 31 sein"
    months = 12
    gutter = 5  # "DD │ "

    plot_cols = months * cols_per_month * cell_w
    cells_per_row = plot_cols // cell_w

    grid = [[" " * cell_w for _ in range(cells_per_row)] for _ in range(height)]
    slots = {(m+1, d+1): 0 for m in range(months) for d in range(height)}

    placed = skipped_format = skipped_range = skipped_empty_emoji = 0

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT name, birthday, COALESCE(emoji,'')
            FROM players
            WHERE birthday IS NOT NULL AND birthday <> ''
        """)
        for name, bday, emo in cur.fetchall():
            s = (bday or "").strip()
            m = BIRTHDAY_RE.match(s)
            if not m:
                skipped_format += 1
                continue
            a, b = int(m.group(1)), int(m.group(2))
            if 1 <= a <= 12 and 1 <= b <= 31:
                mm, dd = a, b
            elif 1 <= b <= 12 and 1 <= a <= 31:
                mm, dd = b, a
            else:
                skipped_range += 1
                continue

            if not (1 <= dd <= 31 and 1 <= mm <= 12):
                skipped_range += 1
                continue
            sym = emo.strip()
            if not sym:
                skipped_empty_emoji += 1
                continue

            row = dd - 1
            month_cell0 = (mm - 1) * cols_per_month
            slot = slots[(mm, dd)]
            cell_idx = month_cell0 + (slot if slot < cols_per_month else cols_per_month - 1)
            if slot < cols_per_month:
                slots[(mm, dd)] = slot + 1
            grid[row][cell_idx] = sym
            placed += 1

    lines = ["Power Ladys Birthday Map"]
    for r in range(height - 1, -1, -1):
        lines.append(f"{r+1:02d} │ " + "".join(grid[r]))

    lines.append(" " * (gutter - 2) + "└" + "─" * plot_cols)

    label_cells = [" "] * cells_per_row
    for mth in range(1, months + 1):
        center_cell = (mth - 1) * cols_per_month + (cols_per_month // 2)
        label_cells[center_cell] = str(mth)
    label_line = "".join(s.center(cell_w) for s in label_cells)
    lines.append(" " * gutter + label_line.rstrip())

    print("```\n" + "\n".join(lines) + "\n```")

# ---------------------------------------------------------------------------

def show_battle(player1_id, player2_id, season_number=None, height=30, max_matches=15, col_width=3):
    """
    Battle-Plot zweier Spieler in einer Season.
    Abwesende werden nicht geplottet.
    """
    import math
    CW = max(2, int(col_width))

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if season_number is None:
            season_number = find_current_season(cur)
        if not season_number:
            print("⚠️ No season.")
            return

        cur.execute("""
            SELECT m.id, m.start
            FROM match m
            WHERE m.season_number = ?
            ORDER BY m.start ASC
        """, (season_number,))
        matches = cur.fetchall()
        if not matches:
            print("⚠️ No matches found.")
            return

        matches = matches[-max_matches:]
        match_ids = [mid for mid, _ in matches]
        n = len(match_ids)

        cur.execute("SELECT id, name, COALESCE(emoji,'') FROM players WHERE id IN (?,?)",
                    (player1_id, player2_id))
        meta = {pid: (name, emoji or "") for pid, name, emoji in cur.fetchall()}

        name1, emo1 = meta.get(player1_id, (f"ID {player1_id}", ""))
        name2, emo2 = meta.get(player2_id, (f"ID {player2_id}", ""))

        if not emo1.strip():
            emo1 = "🅰️"
        if not emo2.strip():
            emo2 = "🅱️"

        q = """
            SELECT ms.match_id, ms.player_id, ms.score, ms.points, ms.absent
            FROM matchscore ms
            WHERE ms.match_id IN ({})
              AND ms.player_id IN (?,?)
        """.format(",".join("?" * len(match_ids)))
        cur.execute(q, match_ids + [player1_id, player2_id])
        rows = cur.fetchall()

        scores = {}
        for mid, pid, score, points, absent in rows:
            if score is None or _is_absent(score, points, absent):
                continue
            scores[(mid, pid)] = score

        vals = list(scores.values())
        if not vals:
            print("⚠️ No scores for these players in this season.")
            return

        vmin, vmax = min(vals), max(vals)
        if vmin == vmax:
            vmin = max(0, vmin - 1000)
            vmax = vmax + 1000
        pad = max(500, int(0.05 * (vmax - vmin)))
        vmin = max(0, (vmin - pad) // 1000 * 1000)
        vmax = math.ceil((vmax + pad) / 1000) * 1000

        def y_to_row(v: int) -> int:
            r = (v - vmin) / (vmax - vmin) if vmax > vmin else 0.5
            return int(round(r * (height - 1)))

        plot_w = n * CW
        grid = [[" "] * plot_w for _ in range(height)]

        def place_cell(row_idx: int, col_x: int, text: str):
            s = (text or "")[:CW]
            leftpad = (CW - len(s)) // 2
            cell = (" " * leftpad) + s
            cell = cell.ljust(CW, " ")
            for k, ch in enumerate(cell):
                pos = col_x + k
                if 0 <= pos < plot_w:
                    grid[row_idx][pos] = ch

        for x, mid in enumerate(match_ids):
            col = x * CW
            here = []
            sc1 = scores.get((mid, player1_id))
            if sc1 is not None:
                r = height - 1 - y_to_row(sc1)
                here.append((r, emo1))
            sc2 = scores.get((mid, player2_id))
            if sc2 is not None:
                r = height - 1 - y_to_row(sc2)
                here.append((r, emo2))

            if len(here) == 2 and here[0][0] == here[1][0]:
                row_idx = here[0][0]
                combo = (here[0][1] + here[1][1])[:CW]
                place_cell(row_idx, col, combo)
            else:
                for row_idx, mark in here:
                    place_cell(row_idx, col, mark)

        tick_rows = {0, height // 4, height // 2, (3 * height) // 4, height - 1}

        print(f"Battle {name1} {emo1} vs {name2} {emo2} (Season {season_number})")
        for r in range(height):
            if r in tick_rows:
                val = vmax - (vmax - vmin) * (r / (height - 1))
                label = f"{int(round(val/1000))}k".rjust(4)
            else:
                label = " " * 4
            print(f"{label}│{''.join(grid[r])}")

        print(" " * 4 + "└" + "─" * plot_w)
        labels = "".join(f"{i+1:>{CW}}" for i in range(n))
        print(" " * 5 + labels)

def show_absent(season_number=None):
    """
    Zeigt unentschuldigte Fehlzeiten aktiver PLTE-Spieler:
    (absent IS NULL oder 0) UND points = 0
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        if season_number is None:
            season_number = find_current_season(cur)
        if not season_number:
            print("⚠️ No matching season found.")
            return

        cur.execute("""
            SELECT p.id, p.name, COUNT(ms.id) AS unexcused
            FROM matchscore ms
            JOIN match m   ON ms.match_id = m.id
            JOIN players p ON ms.player_id = p.id
            WHERE m.season_number = ?
              AND p.active = 1
              AND UPPER(p.team) = 'PLTE'
              AND (ms.absent IS NULL OR ms.absent = 0)
              AND ms.points = 0
            GROUP BY p.id, p.name
            ORDER BY unexcused DESC, p.name ASC
        """, (season_number,))
        rows = cur.fetchall()

        print(f"🚫 Unexcused absences (points=0, absent=0/NULL) – Season {season_number}")
        if not rows:
            print("✅ No unexcused absences.")
            return

        print(f"{'Player':<16} {'Missed':>6}")
        print("-" * 26)
        for pid, name, cnt in rows:
            print(f"{name:<16} {cnt:>6}")

# ---------------------------------------------------------------------------

def _resolve_teamevent_by_offset(cur, offset: int):
    """
    offset 0 = aktuellstes/letztes Teamevent mit Matches,
    1 = davor, 2 = vorletztes, usw.
    Sortiert nach iso_year/iso_week absteigend, Fallback id.
    """
    cur.execute("""
        SELECT DISTINCT t.id, t.name, t.iso_year, t.iso_week
        FROM teamevent t
        JOIN match m ON m.teamevent_id = t.id
        ORDER BY t.iso_year DESC, t.iso_week DESC, t.id DESC
    """)
    rows = cur.fetchall()
    if not rows:
        return None
    if offset < 0 or offset >= len(rows):
        return None
    return rows[offset][0]

def show_teamevent_stats_user(offset: int = 0):
    """
    Wrapper für show_teamevent_stats mit relativem Index:
    offset 0 = aktuellstes Teamevent, 1 = davor, ...
    """
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        te_id = _resolve_teamevent_by_offset(cur, offset)

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
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        # Teamevent-Metadaten holen
        cur.execute("""
            SELECT name, iso_year, iso_week, tracks, max_score_per_track
            FROM teamevent
            WHERE id = ?
        """, (te_id,))
        row = cur.fetchone()
        if not row:
            print(f"⚠️ No teamevent with id {te_id} found.")
            return

        te_name, iso_year, iso_week, te_tracks, te_max = row

        # Alle Matches dieses Teamevents inkl. Scores
        cur.execute("""
            SELECT
                ms.player_id,
                p.name,
                p.team,
                p.active,
                ms.score,
                ms.points,
                ms.absent,
                m.id AS match_id,
                t.tracks,
                t.max_score_per_track
            FROM matchscore ms
            JOIN players   p ON ms.player_id = p.id
            JOIN match     m ON ms.match_id = m.id
            JOIN teamevent t ON m.teamevent_id = t.id
            WHERE m.teamevent_id = ?
        """, (te_id,))
        rows = cur.fetchall()

        if not rows:
            print(f"⚠️ No match scores for teamevent {te_id}.")
            return

        # Scores je Match (alle PLTE, nicht abwesend – active wird NICHT mehr gefiltert)
        scores_by_match = {}
        for pid, name, team, active, score, points, absent, match_id, tracks, max_score in rows:
            if not team or team.upper() != "PLTE":
                continue
            if score is None or _is_absent(score, points, absent):
                continue

            scaled_score = score * 4 / tracks if tracks else score
            scores_by_match.setdefault(match_id, []).append((pid, name, scaled_score))

        if not scores_by_match:
            print(f"⚠️ No valid scores for PLTE players in teamevent {te_id}.")
            return

        # Deltas vs. Median pro Match
        player_scores = {}
        player_names = {}
        player_counts = {}

        import statistics
        for match_id, entries in scores_by_match.items():
            scores = [s for _, _, s in entries]
            if not scores:
                continue
            try:
                median = statistics.median(scores)
            except statistics.StatisticsError:
                continue

            for pid, name, s in entries:
                delta = s - median
                player_scores.setdefault(pid, []).append(delta)
                player_names[pid] = name
                player_counts[pid] = player_counts.get(pid, 0) + 1

        if not player_scores:
            print(f"⚠️ No data to rank for teamevent {te_id}.")
            return

        # Ergebnisliste bauen
        entries = []
        for pid, deltas in player_scores.items():
            avg_delta = round(sum(deltas) / len(deltas))
            count = player_counts.get(pid, 0)
            entries.append((player_names[pid], avg_delta, count))

        # Sortierung wie bei rank: beste Perf zuerst
        entries.sort(key=lambda x: x[1], reverse=True)

        # Header
        print(f"📊 Performance Team Event {te_id}: {te_name} ({iso_year}-W{iso_week})")
        print(f"{'#':>2}   {'Lady':<14} {'Perf':>6} {'Mat.':<2}")
        print("-" * 31)
        for i, (name, delta, count) in enumerate(entries, 1):
            print(f"{i:>2}.  {name:<14} {format_k(delta):>6} {count:>2}")

def show_player_last_matches(player_id: int, last_n: int = 15):
    """
    Shows last N matches of a player:
    - Score, Points
    - Perf delta vs match median (scaled_score = score*4/tracks)
    - Summary: 2 columns (last N | overall), incl. trend (-3 .. +3) aligned in rows
    """

    def _chunks(lst, size=900):
        for i in range(0, len(lst), size):
            yield lst[i:i + size]

    def _linreg_slope(y_vals):
        n = len(y_vals)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(y_vals) / n
        num = den = 0.0
        for i, y in enumerate(y_vals):
            dx = i - x_mean
            dy = y - y_mean
            num += dx * dy
            den += dx * dx
        return num / den if den else 0.0

    def _trend_to_score(slope):
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

    def _fmt_int(v):
        return "-" if v is None else str(int(v))

    def _fmt_k(v):
        return "-" if v is None else format_k(int(round(v)))

    def _print_summary_2col(title_left, title_right, rows, label_w=22, left_w=18, right_w=18):
        sep = label_w + left_w + right_w + 6
        print("-" * sep)
        print(f"{'':<{label_w}} | {title_left:<{left_w}} | {title_right:<{right_w}}")
        print("-" * sep)
        for label, lv, rv in rows:
            print(f"{label:<{label_w}} | {lv:<{left_w}} | {rv:<{right_w}}")
        print("-" * sep)

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        # Player meta
        cur.execute(
            "SELECT name, COALESCE(emoji,''), COALESCE(team,''), active FROM players WHERE id = ?",
            (player_id,),
        )
        row = cur.fetchone()
        if not row:
            print(f"⚠️ No player with id {player_id}.")
            return
        pname, pemoji, pteam, pactive = row
        pemoji = (pemoji or "").strip()

        # Overall totals
        cur.execute("SELECT COUNT(*) FROM matchscore WHERE player_id = ?", (player_id,))
        total_matches_overall = int(cur.fetchone()[0] or 0)

        cur.execute(
            """
            SELECT COUNT(*)
            FROM matchscore
            WHERE player_id = ?
              AND IFNULL(points,0) = 0
              AND (absent IS NULL OR absent = 0)
            """,
            (player_id,),
        )
        total_unexcused_overall = int(cur.fetchone()[0] or 0)

        # Last N matches (desc)
        cur.execute(
            """
            SELECT
                m.id,
                m.start,
                m.season_number,
                t.name,
                t.tracks,
                ms.score,
                ms.points,
                ms.absent
            FROM matchscore ms
            JOIN match     m ON m.id = ms.match_id
            JOIN teamevent t ON t.id = m.teamevent_id
            WHERE ms.player_id = ?
            ORDER BY m.start DESC, m.id DESC
            LIMIT ?
            """,
            (player_id, last_n),
        )
        last_matches = cur.fetchall()
        if not last_matches:
            print(f"⚠️ No matches found for player {player_id}.")
            return

        # Overall matches (chronological)
        cur.execute(
            """
            SELECT
                m.id,
                m.start,
                t.tracks,
                ms.score,
                ms.points,
                ms.absent
            FROM matchscore ms
            JOIN match     m ON m.id = ms.match_id
            JOIN teamevent t ON t.id = m.teamevent_id
            WHERE ms.player_id = ?
            ORDER BY m.start ASC, m.id ASC
            """,
            (player_id,),
        )
        overall_matches = cur.fetchall()
        overall_match_ids = [m[0] for m in overall_matches]

        # Medians per match (PLTE, not absent, score != NULL)
        med_by_match = {}
        if overall_match_ids:
            for chunk in _chunks(overall_match_ids):
                q = f"""
                    SELECT
                        ms.match_id,
                        ms.score,
                        ms.points,
                        ms.absent,
                        p.team,
                        t.tracks
                    FROM matchscore ms
                    JOIN players   p ON p.id = ms.player_id
                    JOIN match     m ON m.id = ms.match_id
                    JOIN teamevent t ON t.id = m.teamevent_id
                    WHERE ms.match_id IN ({",".join("?" * len(chunk))})
                """
                cur.execute(q, chunk)
                rows = cur.fetchall()

                tmp = {}
                for mid, score, points, absent, team, tracks in rows:
                    if not team or team.upper() != "PLTE":
                        continue
                    if score is None or _is_absent(score, points, absent):
                        continue
                    scaled = score * 4 / tracks if tracks else score
                    tmp.setdefault(mid, []).append(float(scaled))

                for mid, vals in tmp.items():
                    if vals:
                        med_by_match[mid] = statistics.median(vals)

        # Header
        head = f"👤 Player {player_id}: {pname}"
        if pemoji:
            head += f" {pemoji}"
        head += f"  (team={pteam or '-'}, active={int(bool(pactive))})"
        print(head)

        print(f"{'#':>2}  {'Start':<10} {'S':>3} {'Match':>5}  {'TeamEvent':<18} {'Score':>6} {'Pts':>4} {'Perf':>6}")
        print("-" * 70)

        # Last N aggregation
        last_counted = last_unexcused = 0
        last_score_sum = last_points_sum = 0
        last_deltas_avg = []
        last_deltas_desc = []

        for i, (mid, start, season, te_name, tracks, score, points, absent) in enumerate(last_matches, 1):
            start_s = (start or "")[:10]
            te_short = (te_name or "")[:18]

            if (points or 0) == 0 and (absent is None or absent == 0):
                last_unexcused += 1

            perf_str = "-"
            if score is not None and not _is_absent(score, points, absent):
                scaled = score * 4 / tracks if tracks else score
                med = med_by_match.get(mid)
                if med is not None:
                    delta = round(scaled - med)
                    perf_str = format_k(delta)
                    last_deltas_avg.append(delta)
                    last_deltas_desc.append(float(scaled - med))
                else:
                    perf_str = "n/a"

                last_counted += 1
                last_score_sum += int(score)
                last_points_sum += int(points or 0)

            score_s = "-" if score is None else str(int(score))
            pts_s = "-" if points is None else str(int(points))

            print(f"{i:>2}. {start_s:<10} {season:>3} {mid:>5}  {te_short:<18} {score_s:>6} {pts_s:>4} {perf_str:>6}")

        # Last N trend needs chronological order
        last_deltas_trend = list(reversed(last_deltas_desc))

        # Overall aggregation
        overall_counted = 0
        overall_score_sum = 0
        overall_points_sum = 0
        overall_deltas = []

        for mid, _, tracks, score, points, absent in overall_matches:
            if score is None or _is_absent(score, points, absent):
                continue
            overall_counted += 1
            overall_score_sum += int(score)
            overall_points_sum += int(points or 0)

            med = med_by_match.get(mid)
            if med is None:
                continue
            scaled = score * 4 / tracks if tracks else score
            overall_deltas.append(float(scaled - med))

        # Averages
        avg_score_last = (last_score_sum / last_counted) if last_counted else None
        avg_points_last = (last_points_sum / last_counted) if last_counted else None
        avg_perf_last = (sum(last_deltas_avg) / len(last_deltas_avg)) if last_deltas_avg else None

        avg_score_overall = (overall_score_sum / overall_counted) if overall_counted else None
        avg_points_overall = (overall_points_sum / overall_counted) if overall_counted else None
        avg_perf_overall = (sum(overall_deltas) / len(overall_deltas)) if overall_deltas else None

        # Trends
        trend_last = _trend_to_score(_linreg_slope(last_deltas_trend) if last_deltas_trend else 0.0)
        trend_overall = _trend_to_score(_linreg_slope(overall_deltas) if overall_deltas else 0.0)

        # Summary table (with trend row)
        rows = [
            ("Match count", _fmt_int(last_counted), _fmt_int(total_matches_overall)),
            ("Unexcused absences", _fmt_int(last_unexcused), _fmt_int(total_unexcused_overall)),
            ("Avg score",
             _fmt_int(round(avg_score_last)) if avg_score_last is not None else "-",
             _fmt_int(round(avg_score_overall)) if avg_score_overall is not None else "-"),
            ("Avg points",
             _fmt_int(round(avg_points_last)) if avg_points_last is not None else "-",
             _fmt_int(round(avg_points_overall)) if avg_points_overall is not None else "-"),
            ("Avg performance", _fmt_k(avg_perf_last), _fmt_k(avg_perf_overall)),
            ("Trend", f"{trend_last:+d}", f"{trend_overall:+d}"),
        ]

        _print_summary_2col(f"last {last_n}", "overall", rows)

