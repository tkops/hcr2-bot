import sqlite3
from typing import Optional
import sys
import re
import textwrap
from datetime import datetime, timedelta

# =====================[ Konfiguration ]=====================
DB_PATH = "../hcr2-db/hcr2.db"
TEAM_RE = re.compile(r"^(PLTE|PL[1-9])$")

# =====================[ CLI Dispatcher ]====================
# die Helfer mit Optional statt "X | None"
ALIAS_BASE_RE = re.compile(r"[^a-z0-9]+")

def _alias_base_from_name(name: str) -> str:
    base = ALIAS_BASE_RE.sub("", (name or "").lower())
    return base or "player"

def _sanitize_alias_token(alias: str) -> str:
    return ALIAS_BASE_RE.sub("", (alias or "").lower())

def _alias_exists(conn: sqlite3.Connection, alias: str, team_scope: Optional[str]) -> bool:
    cur = conn.cursor()
    if team_scope == "PLTE":
        cur.execute("SELECT 1 FROM players WHERE LOWER(alias)=LOWER(?) AND team='PLTE' LIMIT 1", (alias,))
    else:
        cur.execute("SELECT 1 FROM players WHERE LOWER(alias)=LOWER(?) LIMIT 1", (alias,))
    return cur.fetchone() is not None

def _next_free_alias(conn: sqlite3.Connection, base: str, team_scope: Optional[str]) -> Optional[str]:
    for n in range(1, 10):
        candidate = f"{base}{n}"
        if not _alias_exists(conn, candidate, team_scope):
            return candidate
    return None


def handle_command(cmd, args):
    if cmd == "list":
        sort = "gp"
        team = get_arg_value(args, "--team")
        if team:
            team = team.upper()
        if "--sort" in args:
            sort = get_arg_value(args, "--sort") or sort
        show_players(active_only=False, sort_by=sort, team_filter=team)

    elif cmd == "activate":
        if len(args) != 1:
            print("Usage: player activate <id>")
            return
        activate_player(int(args[0]))

    elif cmd == "list-active":
        sort = "gp"
        team = get_arg_value(args, "--team")
        if team:
            team = team.upper()
        if "--sort" in args:
            sort = get_arg_value(args, "--sort") or sort
        show_players(active_only=True, sort_by=sort, team_filter=team)

    elif cmd == "list-leader":
        list_leaders()

    elif cmd == "bday":
        sub = args[0].lower() if args else "today"
        if sub == "today":
            bday_today()
        elif sub == "list":
            active_val = get_arg_value(args, "--active")
            num_val = get_arg_value(args, "--num")
            active_only = parse_bool(active_val, default=False)
            try:
                num = int(num_val) if num_val is not None else None
            except ValueError:
                print("❌ --num expects an integer")
                return
            bday_list(active_only=active_only, num=num)
        else:
            print("Usage: player bday today | player bday list [--active true|false] [--num N]")

    # --- Legacy alias (Kompatibilität) ---
    elif cmd == "birthday":
        bday_today()


    elif cmd == "show":
        # Flags: --id / --name / --discord
        pid_flag = get_arg_value(args, "--id")
        pname_flag = get_arg_value(args, "--name")
        dname_flag = get_arg_value(args, "--discord")

        # Kurzform: player show <id>
        if len(args) == 1 and not args[0].startswith("--"):
            try:
                pid = int(args[0])
                show_player(pid)
            except ValueError:
                print("❌ Invalid ID.")
            return

        # Flags-Variante
        selectors = [x for x in (pid_flag, pname_flag, dname_flag) if x is not None]
        if len(selectors) == 0:
            print("Usage: player show <id> | (--id ID | --name NAME | --discord NAME)")
            return
        if len(selectors) > 1:
            print("❌ Provide exactly one of --id, --name or --discord.")
            return

        pid = _resolve_player_id(player_id=pid_flag, player_name=pname_flag, discord_name=dname_flag)
        if pid is None:
            print("❌ No matching player found.")
            return

        show_player(pid)

    elif cmd == "add":
        if len(args) < 1:
            print("Usage: player add <team> <name> [alias] [gp] [active] [birthday: dd.mm.] [discord_name]")
            print("       alias is required for PLTE and must be unique")
            return

        team_raw = args[0].upper()
        name = args[1] if len(args) > 1 else None
        alias = args[2] if len(args) > 2 else None
        gp = int(args[3]) if len(args) > 3 else 0
        active = args[4].lower() != "false" if len(args) > 4 else True
        birthday_raw = args[5] if len(args) > 5 else None
        discord_name = args[6] if len(args) > 6 else None

        if not name:
            print("❌ Name is required.")
            return

        if not is_valid_team(team_raw):
            print("❌ Invalid team name. Allowed: PLTE or PL1–PL9")
            return

        birthday = parse_birthday(birthday_raw) if birthday_raw else None
        if birthday_raw and not birthday:
            print(f"❌ Invalid birthday format: {birthday_raw} (use DD.MM.)")
            return

        add_player(name=name, alias=alias, gp=gp, active=active,
                   birthday=birthday, team=team_raw, discord_name=discord_name)

    elif cmd == "edit":
        edit_player(args)

    elif cmd == "deactivate":
        if len(args) != 1:
            print("Usage: player deactivate <id>")
            return
        deactivate_player(int(args[0]))

    elif cmd == "delete":
        if len(args) != 1:
            print("Usage: player delete <id>")
            return
        delete_player(int(args[0]))

    elif cmd == "grep":
        if len(args) != 1:
            print("Usage: player grep <term>")
            return
        grep_players(args[0])

    # --- away/back: flexibel per id | name | alias | discord oder Flags ---
    elif cmd == "away":
        # Flags unterstützen
        dur_flag = get_arg_value(args, "--dur")
        pid_flag = get_arg_value(args, "--id")
        pname_flag = get_arg_value(args, "--name")
        dname_flag = get_arg_value(args, "--discord")

        # Kurzform: player away <term> [1w|2w|3w|4w]
        term = None
        dur_pos = None
        if args and not args[0].startswith("--"):
            term = args[0]
            if len(args) > 1 and not args[1].startswith("--"):
                dur_pos = args[1]

        dur = dur_flag or dur_pos
        if pid_flag or pname_flag or dname_flag:
            away_set_generic(player_id=pid_flag, player_name=pname_flag,
                             discord_name=dname_flag, dur_token=dur)
        elif term:
            away_set_fuzzy(term, dur)
        else:
            print("Usage: player away (<term> [1w|2w|3w|4w]) | (--id ID | --name NAME | --discord NAME) [--dur 1w|2w|3w|4w]")

    elif cmd == "back":
        # Flags
        pid_flag = get_arg_value(args, "--id")
        pname_flag = get_arg_value(args, "--name")
        dname_flag = get_arg_value(args, "--discord")

        # Kurzform: player back <term>
        term = None
        if args and not args[0].startswith("--"):
            term = args[0]

        if pid_flag or pname_flag or dname_flag:
            away_clear_generic(player_id=pid_flag, player_name=pname_flag, discord_name=dname_flag)
        elif term:
            away_clear_fuzzy(term)
        else:
            print("Usage: player back <term> | (--id ID | --name NAME | --discord NAME)")

    else:
        print(f"❌ Unknown player command: {cmd}")
        print_help()

# =====================[ Helpers: Common ]==================
def db():
    """Open connection with dict-like rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = lambda cur, row: {d[0]: row[i] for i, d in enumerate(cur.description)}
    return conn

def parse_bool(s, default=False):
    if s is None:
        return default
    v = s.strip().lower()
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    return default

def _days_until_mmdd(mmdd: str):
    """Gibt Tage bis zum nächsten Auftreten von MM-DD zurück (ab heute)."""
    from datetime import date
    try:
        m, d = map(int, mmdd.split("-"))
    except Exception:
        return None
    today = date.today()
    # handle 29.02 in Nicht-Schaltjahren → auf 01.03 schieben
    def safe_date(y, m, d):
        try:
            return date(y, m, d)
        except ValueError:
            # 29.02 → 01.03 (einfachste robuste Wahl)
            if m == 2 and d == 29:
                return date(y, 3, 1)
            return None
    target = safe_date(today.year, m, d)
    if target is None:
        return None
    if target < today:
        target = safe_date(today.year + 1, m, d)
        if target is None:
            return None
    return (target - today).days


def get_arg_value(args, key):
    if key in args:
        idx = args.index(key)
        if idx + 1 < len(args):
            return args[idx + 1]
    return None

def parse_birthday(raw):
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw.strip("."), "%d.%m")
        return dt.strftime("%m-%d")
    except ValueError:
        return None

def _print_wrapped(label, text, width=60, indent=15):
    if not text:
        text = "-"
    wrapper = textwrap.TextWrapper(width=width, subsequent_indent=" " * (indent + 2))
    wrapped = wrapper.fill(text)
    print(f"{label:<{indent}}: {wrapped}")

def format_birthday(stored):
    if not stored:
        return "-"
    try:
        dt = datetime.strptime(stored, "%m-%d")
        return dt.strftime("%d.%m.")
    except ValueError:
        return stored

def is_valid_team(team):
    return bool(TEAM_RE.fullmatch(team))

def today_mm_dd():
    return datetime.now().strftime("%m-%d")

# =====================[ Unified Search ]===================
def search_players_like(term: str):
    """LIKE-Suche über name/alias/discord; sortiert by name (case-insensitive)."""
    pat = f"%{term.lower()}%"
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, alias, garage_power, active,
                   COALESCE(discord_name,'') AS discord_name
            FROM players
            WHERE LOWER(name) LIKE ?
               OR LOWER(alias) LIKE ?
               OR LOWER(COALESCE(discord_name,'')) LIKE ?
            ORDER BY name COLLATE NOCASE
        """, (pat, pat, pat))
        return cur.fetchall()

def resolve_player_id_exact(term: str):
    """Exakte Auflösung: numerische ID bzw. exakter Name/Alias/Discord (case-insensitive)."""
    if term.isdigit():
        pid = int(term)
        with db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM players WHERE id = ?", (pid,))
            r = cur.fetchone()
            return r["id"] if r else None

    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM players
            WHERE LOWER(name) = LOWER(?)
               OR LOWER(alias) = LOWER(?)
               OR LOWER(COALESCE(discord_name,'')) = LOWER(?)
        """, (term, term, term))
        rows = cur.fetchall()

    if len(rows) == 1:
        return rows[0]["id"]
    return None  # 0 oder >1

def resolve_player_id_fuzzy(term: str, *, print_when_ambiguous=True):
    """Exakt → sonst LIKE. Eindeutig? → ID, sonst drucke Liste & None."""
    pid = resolve_player_id_exact(term)
    if pid is not None:
        return pid

    rows = search_players_like(term)
    if len(rows) == 0:
        print(f"❌ No players found matching '{term}'")
        return None
    if len(rows) == 1:
        return rows[0]["id"]

    if print_when_ambiguous:
        print(f"⚠️  Term '{term}' is not unique. Matching players:")
        print(f"{'ID':<4} {'NAME':<20} {'Alias':<15} {'Discord':<22} {'GP':>5} {'Act':>5}")
        print("-" * 74)
        for r in rows:
            print(f"{r['id']:<4} {r['name']:<20} {r['alias'] or '':<15} {r['discord_name'] or '':<22} {r['garage_power']:>5} {str(bool(r['active']))[:1]}")
        print("-" * 74)
    return None

def grep_players(term):
    rows = search_players_like(term)
    if not rows:
        print(f"❌ No players found matching '{term}'")
        return

    print(f"{'ID':<4} {'NAME':<20} {'Alias':<15} {'Discord':<22} {'GP':>5} {'Act':>5}")
    print("-" * 74)
    for r in rows:
        print(f"{r['id']:<4} {r['name']:<20} {r['alias'] or '':<15} {r['discord_name'] or '':<22} {r['garage_power']:>5} {str(bool(r['active']))[:1]}")
    print("-" * 74)

# =====================[ Listen & Anzeigen ]================

def show_players(active_only=False, sort_by="gp", team_filter=None):
    with db() as conn:
        cur = conn.cursor()
        q = """
            SELECT id, name, alias, garage_power, active, created_at,
                   birthday, team, COALESCE(discord_name,'-') AS discord_name,
                   COALESCE(is_leader,0) AS is_leader,
                   active_modified, away_until
            FROM players
        """
        cond, params = [], []
        if active_only:
            cond.append("active = 1")
        if team_filter:
            cond.append("UPPER(team) = ?")
            params.append(team_filter.upper())
        if cond:
            q += " WHERE " + " AND ".join(cond)

        # Spezialfall: list-active --team <X> → nach active_modified aufsteigend (neueste unten)
        if active_only and team_filter:
            q += " ORDER BY datetime(active_modified) ASC"
        else:
            q += " ORDER BY " + ("name COLLATE NOCASE" if sort_by == "name" else "garage_power DESC")

        cur.execute(q, params)
        rows = cur.fetchall()

        # Schlanke Ausgabe für list-active --team <X>
        if team_filter and active_only:
            print(f"{'#':<3} {'ID':<4} {'Name':<20} {'✈️':<3}")
            print("-" * 32)
            for i, r in enumerate(rows, start=1):
                abs_mark = "x" if r["away_until"] and r["away_until"] > datetime.now().strftime("%Y-%m-%d %H:%M:%S") else ""
                print(f"{i:<3} {r['id']:<4} {r['name']:<20} {abs_mark:<3}")
            print("-" * 32)
            return

        # Bisherige Team-Ansicht (nur --team, ohne list-active)
        if team_filter:
            print(f"{'#':<3} {'ID':<4} {'Name':<20} {'Alias':<15} {'Leader':<6} {'ABS':<3}")
            print("-" * 80)
            for i, r in enumerate(rows, start=1):
                abs_mark = "x" if r["away_until"] and r["away_until"] > datetime.now().strftime("%Y-%m-%d %H:%M:%S") else ""
                print(f"{i:<3} {r['id']:<4} {r['name']:<20} {r['alias'] or '-':<15} {bool(r['is_leader']):<6} {abs_mark:<3}")
            print("-" * 80)
            return

        # Standard-Gesamtansicht
        cur.execute("SELECT COUNT(*) AS cnt FROM players WHERE active = 1")
        active_count = cur.fetchone()["cnt"]

        print(f"{'ID':<4} {'Name':<20} {'Alias':<15} {'GP':>6} {'Act':<5} {'Lead':<5} {'Birthday':<10} {'Team':<7} {'Discord':<18} {'Created':<20} {'ABS':<3}")
        print("-" * 140)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for r in rows:
            bday_fmt = format_birthday(r["birthday"])
            abs_mark = "x" if r["away_until"] and r["away_until"] > now else ""
            created = (r["created_at"] or "-")[:19]
            print(
                f"{r['id']:<4} "
                f"{(r['name'] or '-'):<20} "
                f"{(r['alias'] or '-'):<15} "
                f"{int(r['garage_power']):>6} "
                f"{str(bool(r['active'])):<5} "
                f"{str(bool(r['is_leader'])):<5} "
                f"{bday_fmt:<10} "
                f"{(r['team'] or '-'):<7} "
                f"{(r['discord_name'] or '-'):<18} "
                f"{created:<20} "
                f"{abs_mark:<3}"
            )
        print("-" * 140)
        print(f"Active players: {active_count}")


def list_leaders():
    """Listet alle Spieler mit is_leader = 1 (unabhängig von 'active')."""
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, COALESCE(discord_name, '-') AS discord_name
            FROM players
            WHERE COALESCE(is_leader, 0) = 1
            ORDER BY name COLLATE NOCASE
        """)
        rows = cur.fetchall()

    if not rows:
        print("❌ No leaders found.")
        return

    print(f"{'ID':<4} {'Name':<25} {'Discord':<30}")
    print("-" * 64)
    for r in rows:
        print(f"{r['id']:<4} {r['name']:<25} {r['discord_name']:<30}")
    print("-" * 64)
    print(f"👑 Leaders: {len(rows)}")


def bday_today():
    """Druckt 'BIRTHDAY_IDS: 12,45,78' für HEUTE (eine Zeile)."""
    today = today_mm_dd()
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id
            FROM players
            WHERE birthday = ?
            ORDER BY name COLLATE NOCASE
        """, (today,))
        ids = [str(r["id"]) for r in cur.fetchall()]
    if ids:
        print("BIRTHDAY_IDS: " + ",".join(ids))

# Legacy-Alias für Alt-Code
def birthday_command():
    bday_today()

def bday_list(*, active_only=False, num=None):
    """Listet Geburtstage (ID, Name, Geburtstag, Emoji), sortiert nach nächstem Termin."""
    with db() as conn:
        cur = conn.cursor()
        q = """
            SELECT id, name, birthday, COALESCE(emoji,'') AS emoji, COALESCE(active,0) AS active
            FROM players
            WHERE birthday IS NOT NULL AND birthday != ''
        """
        if active_only:
            q += " AND active = 1"
        cur.execute(q)
        rows = cur.fetchall()

    items = []
    for r in rows:
        mmdd = r["birthday"]
        du = _days_until_mmdd(mmdd) if mmdd else None
        if du is None:
            continue
        items.append((du, r))

    items.sort(key=lambda x: x[0])
    if num is not None and num >= 0:
        items = items[:num]

    print(f"{'ID':<4} {'Name':<20} {'Birthday':<10} {'Emoji'}")
    print("-" * 43)
    for du, r in items:
        print(f"{r['id']:<4} {r['name']:<20} {format_birthday(r['birthday']):<10} {r['emoji']}")
    print("-" * 43)
    scope = "(active only)" if active_only else "(all)"
    print(f"Count: {len(items)} {scope}")

def show_player(pid: int):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, alias, garage_power, active, birthday, team, discord_name,
                   created_at, last_modified, active_modified, away_from, away_until,
                   COALESCE(is_leader, 0) AS is_leader,
                   about, preferred_vehicles, playstyle, language, emoji
            FROM players
            WHERE id = ?
        """, (pid,))
        r = cur.fetchone()

    if not r:
        print(f"❌ Player ID {pid} not found.")
        return

    print(f"{'ID':<15}: {r['id']}")
    print(f"{'Name':<15}: {r['name']}")
    print(f"{'Alias':<15}: {r['alias'] or '-'}")
    print(f"{'Garage Power':<15}: {r['garage_power']}")
    print(f"{'Active':<15}: {bool(r['active'])}")
    print(f"{'Leader':<15}: {bool(r['is_leader'])}")
    print(f"{'Birthday':<15}: {format_birthday(r['birthday'])}")
    print(f"{'Team':<15}: {r['team'] or '-'}")
    print(f"{'Discord':<15}: {r['discord_name'] or '-'}")
    print(f"{'Created':<15}: {r['created_at']}")
    print(f"{'Last modified':<15}: {r['last_modified'] or '-'}")
    print(f"{'Active modified':<15}: {r['active_modified'] or '-'}")
    print(f"{'Away from':<15}: {r['away_from'] or '-'}")
    print(f"{'Away until':<15}: {r['away_until'] or '-'}")
    _print_wrapped("About", r['about'])
    _print_wrapped("Vehicles", r['preferred_vehicles'])
    _print_wrapped("Playstyle", r['playstyle'])
    _print_wrapped("Language", r['language'])
    _print_wrapped("Emoji", r['emoji'])

# =====================[ Mutationen ]=======================

def add_player(name, alias=None, gp=0, active=True, birthday=None, team=None, discord_name=None):
    """
    - Alias wird sanitisiert (nur [a-z0-9]).
    - Falls kein Alias angegeben oder (bei PLTE) leer → aus Name erzeugen + Ziffernsuffix 1..9 (eindeutig).
    - Nach Insert wird die neue ID ausgegeben.
    """
    team = (team or "").upper().strip()
    if not is_valid_team(team):
        print("❌ Invalid team name. Allowed: PLTE or PL1–PL9")
        return

    # 1) Alias vorbereiten/sanitisieren
    alias = _sanitize_alias_token(alias) if alias else None
    alias_generated = False

    with db() as conn:
        cur = conn.cursor()

        # 2) Für PLTE ist Alias-Pflicht → wenn fehlt, automatisch generieren
        #    Für andere Teams: Alias optional; wenn fehlt, wird NICHT erzwungen – außer du möchtest es global.
        if team == "PLTE":
            if not alias:
                base = _alias_base_from_name(name)
                alias_candidate = _next_free_alias(conn, base, team_scope="PLTE")
                if not alias_candidate:
                    print(f"❌ Could not generate unique alias for base '{base}' (1..9 all taken).")
                    return
                alias = alias_candidate
                alias_generated = True
            else:
                # expliziter Alias → prüfen, ob exakt belegt in PLTE
                if _alias_exists(conn, alias, team_scope="PLTE"):
                    print(f"❌ Alias conflict in PLTE: '{alias}' already exists.")
                    return
        else:
            # Nicht-PLTE: sanitizen; Doppelt erlaubt, aber falls du global Eindeutigkeit willst:
            # if alias and _alias_exists(conn, alias, team_scope=None):
            #     print(f"❌ Alias conflict: '{alias}' already exists.")
            #     return
            pass

        # 3) Insert
        cur.execute("""
            INSERT INTO players (name, alias, garage_power, active, birthday, team, discord_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, alias, gp, int(active), birthday, team, discord_name))
        new_id = cur.lastrowid

    alias_info = f" | Alias: {alias}" if alias else ""
    gen_info = " (generated)" if alias_generated else ""
    print(f"✅ Player '{name}' added. ID: {new_id}{alias_info}{gen_info} | Team: {team}")


def edit_player(args):
    if len(args) < 1:
        print("Usage: player edit <id>"
              " [--name NAME] [--alias ALIAS] [--gp GP] [--active true|false]"
              " [--birthday DD.MM.] [--team TEAM] [--discord DISCORD] [--leader true|false]"
              " [--about TEXT] [--vehicles TEXT] [--playstyle TEXT] [--language TEXT] [--emoji EMOJI]")
        return

    pid = int(args[0])
    name = alias = birthday = team = discord = None
    gp = active = leader = None
    about = vehicles = playstyle = language = emoji = None

    i = 1
    while i < len(args):
        if args[i] == "--name":
            i += 1; name = args[i]
        elif args[i] == "--alias":
            i += 1; alias = args[i]
        elif args[i] == "--gp":
            i += 1; gp = int(args[i])
        elif args[i] == "--active":
            i += 1
            val = args[i].lower()
            if val not in ("true", "false", "1", "0"):
                print("❌ --active expects true|false"); return
            active = (val in ("true", "1"))
        elif args[i] == "--leader":
            i += 1
            val = args[i].lower()
            if val not in ("true", "false", "1", "0"):
                print("❌ --leader expects true|false"); return
            leader = (val in ("true", "1"))
        elif args[i] == "--birthday":
            i += 1
            raw = args[i]; birthday = parse_birthday(raw)
            if not birthday:
                print(f"❌ Invalid birthday format: {raw} (use DD.MM.)"); return
        elif args[i] == "--team":
            i += 1
            team = args[i].upper()
            if not is_valid_team(team):
                print(f"❌ Invalid team name: {team} (allowed: PLTE or PL1–PL9)"); return
        elif args[i] == "--discord":
            i += 1; discord = args[i]
        elif args[i] == "--about":
            i += 1; about = args[i]
        elif args[i] == "--vehicles":
            i += 1; vehicles = args[i]
        elif args[i] == "--playstyle":
            i += 1; playstyle = args[i]
        elif args[i] == "--language":
            i += 1; language = args[i]
        elif args[i] == "--emoji":
            i += 1; emoji = args[i]
        i += 1

    if alias is not None:
        alias = alias.strip()

    with db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT team, alias FROM players WHERE id = ?", (pid,))
        row = cur.fetchone()
        if not row:
            print(f"❌ Player ID {pid} not found.")
            return
        current_team, current_alias = row["team"], row["alias"]
        target_team = team or current_team
        target_alias = alias if alias is not None else current_alias

        if target_team == "PLTE":
            if not target_alias:
                print("❌ Alias is required for team PLTE."); return
            cur.execute("""
                SELECT id, alias FROM players
                WHERE team = 'PLTE' AND id != ?
            """, (pid,))
            for r in cur.fetchall():
                calias = r["alias"]
                if target_alias in calias or calias in target_alias:
                    print(f"❌ Alias conflict: '{target_alias}' vs '{calias}' (ID {r['id']})")
                    return

        fields, values = [], []
        if name is not None:        fields += ["name = ?"];               values += [name]
        if alias is not None:       fields += ["alias = ?"];              values += [alias]
        if gp is not None:          fields += ["garage_power = ?"];       values += [gp]
        if active is not None:      fields += ["active = ?"];             values += [1 if active else 0]
        if birthday is not None:    fields += ["birthday = ?"];           values += [birthday]
        if team is not None:        fields += ["team = ?"];               values += [team]
        if discord is not None:     fields += ["discord_name = ?"];       values += [discord]
        if leader is not None:      fields += ["is_leader = ?"];          values += [1 if leader else 0]
        if about is not None:       fields += ["about = ?"];              values += [about]
        if vehicles is not None:    fields += ["preferred_vehicles = ?"]; values += [vehicles]
        if playstyle is not None:   fields += ["playstyle = ?"];          values += [playstyle]
        if language is not None:    fields += ["language = ?"];           values += [language]
        if emoji is not None:       fields += ["emoji = ?"];              values += [emoji]

        if not fields:
            print("⚠️  Nothing to update.")
            return

        values.append(pid)
        query = f"UPDATE players SET {', '.join(fields)} WHERE id = ?"
        conn.execute(query, values)

    print(f"✅ Player {pid} updated.")
    show_player(pid)

def deactivate_player(pid):
    with db() as conn:
        conn.execute("UPDATE players SET active = 0 WHERE id = ?", (pid,))
    print(f"🟡 Player {pid} deactivated.")

def delete_player(pid):
    with db() as conn:
        conn.execute("DELETE FROM players WHERE id = ?", (pid,))
    print(f"🗑️  Player {pid} deleted.")

def activate_player(pid):
    with db() as conn:
        conn.execute("UPDATE players SET active = 1 WHERE id = ?", (pid,))
    print(f"🟢 Player {pid} activated.")

# =====================[ Away / Back ]======================
def _parse_weeks_token(token):
    """Accepts 1w..4w (optional 'w'); returns days 7..28. Default 1w."""
    if not token:
        return 7
    m = re.fullmatch(r"\s*([1-4])\s*w?\s*", token, flags=re.IGNORECASE)
    if not m:
        raise ValueError("Use 1w, 2w, 3w or 4w.")
    return int(m.group(1)) * 7

def _parse_weeks_token_or_default(token):
    try:
        return _parse_weeks_token(token)
    except ValueError as e:
        print(f"❌ {e}")
        return None

def _fetch_player_brief(pid: int):
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, alias, discord_name
            FROM players
            WHERE id = ?
        """, (pid,))
        return cur.fetchone()  # dict or None

def away_set_fuzzy(term, dur_token):
    pid = resolve_player_id_fuzzy(term)
    if pid is None:
        return
    away_set_generic(player_id=str(pid), player_name=None, discord_name=None, dur_token=dur_token)

def away_clear_fuzzy(term):
    pid = resolve_player_id_fuzzy(term)
    if pid is None:
        return
    away_clear_generic(player_id=str(pid), player_name=None, discord_name=None)

def away_set_generic(player_id=None, player_name=None, discord_name=None, dur_token=None):
    # Falls per Flags übergeben wurde → auflösen
    if player_id or player_name or discord_name:
        pid = _resolve_player_id(player_id, player_name, discord_name)
        if pid is None:
            return
    else:
        print("❌ Provide one of --id, --name, --discord or use the short form with a term.")
        return

    days = _parse_weeks_token_or_default(dur_token)
    if days is None:
        return

    now = datetime.now()
    away_from = now.strftime("%Y-%m-%d %H:%M:%S")
    away_until = (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    with db() as conn:
        conn.execute("""
            UPDATE players
               SET away_from = ?, away_until = ?
             WHERE id = ?
        """, (away_from, away_until, pid))

    brief = _fetch_player_brief(pid)
    if brief:
        _id, name, alias, discord = brief["id"], brief["name"], brief["alias"], brief["discord_name"]
        print(
            "✅ Away set\n"
            f"Player       : ID {_id} | Name: {name} | Alias: {alias or '-'} | Discord: {discord or '-'}\n"
            f"From → Until : {away_from}  →  {away_until}"
        )
    else:
        print(f"✅ Away set for player {pid}\nfrom: {away_from}\nuntil: {away_until}")

def away_clear_generic(player_id=None, player_name=None, discord_name=None):
    pid = _resolve_player_id(player_id, player_name, discord_name)
    if pid is None:
        return
    with db() as conn:
        conn.execute("""
            UPDATE players
               SET away_from = NULL, away_until = NULL
             WHERE id = ?
        """, (pid,))

    brief = _fetch_player_brief(pid)
    if brief:
        _id, name, alias, discord = brief["id"], brief["name"], brief["alias"], brief["discord_name"]
        print(
            "✅ Back: absence cleared\n"
            f"Player: ID {_id} | {name} | alias: {alias or '-'} | discord: {discord or '-'}"
        )
    else:
        print(f"✅ Back: absence cleared for player {pid}")

def _resolve_player_id(player_id=None, player_name=None, discord_name=None):
    """Resolve a single player id from explicit flags."""
    if player_id:
        try:
            return int(player_id)
        except ValueError:
            print("❌ Invalid --id value")
            return None

    if discord_name:
        with db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id FROM players
                WHERE LOWER(discord_name) = LOWER(?)
            """, (discord_name.strip(),))
            rows = cur.fetchall()
        if not rows:
            print(f"❌ No player found for discord_name='{discord_name}'")
            return None
        if len(rows) > 1:
            _ = search_players_like(discord_name)
            print(f"⚠️ Multiple players match '{discord_name}'.")
            return None
        return rows[0]["id"]

    if player_name:
        with db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id FROM players
                WHERE LOWER(name) = LOWER(?)
            """, (player_name.strip(),))
            rows = cur.fetchall()
        if not rows:
            return resolve_player_id_fuzzy(player_name)
        if len(rows) > 1:
            _ = search_players_like(player_name)
            print(f"⚠️ Multiple players match '{player_name}'.")
            return None
        return rows[0]["id"]

    print("❌ Provide one of --id, --name, or --discord")
    return None

# =====================[ Hilfe ]============================

def print_help():
    print("Usage: python hcr2.py player <command> [args]")
    print("\nAvailable commands:")
    print("  list [--sort gp|name] [--team TEAM]         Show all players")
    print("  list-active [--sort gp|name] [--team TEAM]  Show only active players")
    print("  list-leader                                 Show only leaders (id, name, discord)")
    print("  bday today                                 Print 'BIRTHDAY_IDS: ...' for today's birthdays")
    print("  bday list [--active true|false] [--num N]  List birthdays (ID, Name, Birthday, Emoji), sorted by next upcoming")
    print("  add <team> <name> [alias] [gp] [active] [birthday: dd.mm.] [discord_name]")
    print("  edit <id>                                   Edit fields, e.g.:")
    print("      --name NAME --alias ALIAS --gp 90000 --active true|false")
    print("      --birthday 15.07. --team PL3 --discord foo#1234")
    print("      --leader true|false --about '...' --vehicles '...'")
    print("      --playstyle '...' --language en --emoji '🚗'")
    print("  deactivate <id>               Set player inactive")
    print("  delete <id>                   Remove player")
    print("  show <id> | (--id ID | --name NAME | --discord NAME)")
    print("  grep <term>                   Search players by name/alias/discord (case-insensitive)")
    print("  activate <id>                 Set player active")
    print("  away (<term> [1w|2w|3w|4w]) | (--id ID | --name NAME | --discord NAME) [--dur 1w|2w|3w|4w]")
    print("  back <term> | (--id ID | --name NAME | --discord NAME)")


