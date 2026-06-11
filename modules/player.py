import sqlite3
from typing import Optional
import sys
import re
import textwrap
from datetime import datetime, timedelta
from modules.common import (
    DB_PATH,
    connect_dict_db,
    get_arg_value,
    is_help_request,
    parse_bool,
    print_command_help,
    print_unknown_command,
)

# =====================[ Configuration ]=====================
TEAM_RE = re.compile(r"^(PLTE|PL[1-9])$")
USAGE_ACTIVATE = "Usage: player activate <id> | --id <id>"
USAGE_DEACTIVATE = "Usage: player deactivate <id> | --id <id>"
USAGE_DELETE = "Usage: player delete <id> | --id <id>"
USAGE_ADD = (
    "Usage: player add <team> <name> [alias] [gp] [active] [birthday: dd.mm.] [discord_name] "
    "| --team <team> --name <name> [--alias <alias>] [--gp <gp>] [--active true|false] "
    "[--birthday <dd.mm.>] [--discord <name>]"
)
USAGE_EDIT = (
    "Usage: player edit <id> [--name NAME] [--alias ALIAS] [--gp GP] [--active true|false] "
    "[--birthday DD.MM.] [--team TEAM] [--discord DISCORD] [--leader true|false] "
    "[--about TEXT] [--vehicles TEXT] [--playstyle TEXT] [--language TEXT] [--emoji EMOJI] "
    "| --id <id> [same flags]"
)
USAGE_GREP = "Usage: player grep <term>"
USAGE_SHOW = "Usage: player show <id> | (--id ID | --name NAME | --discord NAME)"
USAGE_BDAY = "Usage: player bday today | player bday list [--active true|false] [--num N]"
USAGE_AWAY = "Usage: player away (<term> [1w|2w|3w|4w]) | (--id ID | --name NAME | --discord NAME) [--dur 1w|2w|3w|4w]"
USAGE_BACK = "Usage: player back <term> | (--id ID | --name NAME | --discord NAME)"

# =====================[ CLI Dispatcher ]====================
# Helpers use Optional instead of "X | None".
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
    if is_help_request(cmd, *args):
        print_help()
        return

    handlers = {
        "list": _handle_list,
        "activate": _handle_activate,
        "list-absent": _handle_list_absent,
        "list-active": _handle_list_active,
        "list-leader": _handle_list_leader,
        "bday": _handle_bday,
        "birthday": _handle_birthday,
        "show": _handle_show,
        "add": _handle_add,
        "edit": _handle_edit,
        "deactivate": _handle_deactivate,
        "delete": _handle_delete,
        "grep": _handle_grep,
        "away": _handle_away,
        "back": _handle_back,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print_unknown_command("player", cmd)
        print_help()
        return
    handler(args)


def _parse_required_int_arg(args, usage):
    if not args:
        print(usage)
        return None
    raw = get_arg_value(args, "--id") if "--id" in args else args[0]
    try:
        return int(raw)
    except ValueError:
        print(usage)
        return None


def _extract_list_options(args):
    sort = "gp"
    team = get_arg_value(args, "--team")
    if team:
        team = team.upper()
    if "--sort" in args:
        sort = get_arg_value(args, "--sort") or sort
    return sort, team


def _handle_list(args):
    sort, team = _extract_list_options(args)
    show_players(active_only=False, sort_by=sort, team_filter=team)


def _handle_activate(args):
    pid = _parse_required_int_arg(args, USAGE_ACTIVATE)
    if pid is None:
        return
    activate_player(pid)


def _handle_list_absent(args):
    if args:
        print("Usage: player list-absent")
        return
    list_absent()


def _handle_list_active(args):
    sort, team = _extract_list_options(args)
    show_players(active_only=True, sort_by=sort, team_filter=team)


def _handle_list_leader(args):
    if args:
        print("Usage: player list-leader")
        return
    list_leaders()


def _handle_bday(args):
    sub = args[0].lower() if args else "today"
    if sub == "today":
        bday_today()
        return
    if sub == "list":
        active_val = get_arg_value(args, "--active")
        num_val = get_arg_value(args, "--num")
        active_only = parse_bool(active_val, default=False)
        try:
            num = int(num_val) if num_val is not None else None
        except ValueError:
            print("❌ --num expects an integer")
            return
        bday_list(active_only=active_only, num=num)
        return
    print(USAGE_BDAY)


def _handle_birthday(args):
    if args:
        print("Usage: player birthday")
        return
    bday_today()


def _handle_show(args):
    pid_flag = get_arg_value(args, "--id")
    pname_flag = get_arg_value(args, "--name")
    dname_flag = get_arg_value(args, "--discord")

    if len(args) == 1 and not args[0].startswith("--"):
        try:
            pid = int(args[0])
            show_player(pid)
        except ValueError:
            print("❌ Invalid ID.")
        return

    selectors = [x for x in (pid_flag, pname_flag, dname_flag) if x is not None]
    if len(selectors) == 0:
        print(USAGE_SHOW)
        return
    if len(selectors) > 1:
        print("❌ Provide exactly one of --id, --name or --discord.")
        return

    pid = _resolve_player_id(player_id=pid_flag, player_name=pname_flag, discord_name=dname_flag)
    if pid is None:
        print("❌ No matching player found.")
        return

    show_player(pid)


def _handle_add(args):
        if len(args) < 1:
            print(USAGE_ADD)
            print("       alias is required for PLTE and must be unique")
            return

        if args[0].startswith("--"):
            team_token = get_arg_value(args, "--team")
            name = get_arg_value(args, "--name")
            alias = get_arg_value(args, "--alias")
            gp_token = get_arg_value(args, "--gp")
            active_token = get_arg_value(args, "--active")
            birthday_raw = get_arg_value(args, "--birthday")
            discord_name = get_arg_value(args, "--discord")

            if not team_token or not name:
                print(USAGE_ADD)
                return

            team_raw = team_token.upper()
            try:
                gp = int(gp_token) if gp_token is not None else 0
            except ValueError:
                print("❌ --gp expects an integer.")
                return
            active = parse_bool(active_token, default=True)
        else:
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


def _handle_edit(args):
    edit_player(args)


def _handle_deactivate(args):
    pid = _parse_required_int_arg(args, USAGE_DEACTIVATE)
    if pid is None:
        return
    deactivate_player(pid)


def _handle_delete(args):
    pid = _parse_required_int_arg(args, USAGE_DELETE)
    if pid is None:
        return
    delete_player(pid)


def _handle_grep(args):
    if len(args) != 1:
        print(USAGE_GREP)
        return
    grep_players(args[0])


def _handle_away(args):
    dur_flag = get_arg_value(args, "--dur")
    pid_flag = get_arg_value(args, "--id")
    pname_flag = get_arg_value(args, "--name")
    dname_flag = get_arg_value(args, "--discord")

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
        print(USAGE_AWAY)


def _handle_back(args):
    pid_flag = get_arg_value(args, "--id")
    pname_flag = get_arg_value(args, "--name")
    dname_flag = get_arg_value(args, "--discord")

    term = None
    if args and not args[0].startswith("--"):
        term = args[0]

    if pid_flag or pname_flag or dname_flag:
        away_clear_generic(player_id=pid_flag, player_name=pname_flag, discord_name=dname_flag)
    elif term:
        away_clear_fuzzy(term)
    else:
        print(USAGE_BACK)

# =====================[ Helpers: Common ]==================
def db():
    """Open connection with dict-like rows."""
    return connect_dict_db()

def _days_until_mmdd(mmdd: str):
    """Return days until the next occurrence of MM-DD, starting today."""
    from datetime import date
    try:
        m, d = map(int, mmdd.split("-"))
    except Exception:
        return None
    today = date.today()
    # Move 02-29 to 03-01 in non-leap years.
    def safe_date(y, m, d):
        try:
            return date(y, m, d)
        except ValueError:
            # 02-29 -> 03-01 as the simplest robust choice.
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
    """LIKE search over name/alias/discord, sorted by name (case-insensitive)."""
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
    """Resolve exactly: numeric ID or exact name/alias/discord (case-insensitive)."""
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
    return None  # 0 or >1

def resolve_player_id_fuzzy(term: str, *, print_when_ambiguous=True):
    """Try exact match first, then LIKE. Return ID if unique; otherwise print matches and return None."""
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

def list_absent():
    now = datetime.now().date()
    with db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, team, away_until
            FROM players
            WHERE away_from IS NOT NULL
              AND away_until IS NOT NULL
              AND datetime(away_from) <= datetime('now')
              AND datetime(away_until) >= datetime('now')
        """)
        rows = cur.fetchall()

    items = []
    for r in rows:
        try:
            until_dt = datetime.strptime(r["away_until"][:19], "%Y-%m-%d %H:%M:%S")
            days = max(0, (until_dt.date() - now).days)
        except Exception:
            until_dt = None
            days = 0
        items.append((days, r["id"], r["name"] or "-", r["team"] or "-", r["away_until"][:19] if r["away_until"] else "-"))

    # Sort by DAYS descending.
    items.sort(key=lambda x: x[0], reverse=True)

    print("🛫 Absent Ladies")
    print(f"{'ID':<4} {'NAME':<20} {'TEAM':<6} {'UNTIL':<19} {'DAYS':>4}")
    print("-" * 58)
    for days, pid, name, team, until_str in items:
        print(f"{pid:<4} {name:<20} {team:<6} {until_str:<19} {days:>4}")
    print("-" * 58)
    print(f"Count: {len(items)}")


# =====================[ Lists & Display ]================

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

        # Special case: list-active --team <X> sorts by GP and displays GP without the absent column.
        if team_filter and active_only:
            q += " ORDER BY garage_power DESC"
            cur.execute(q, params)
            rows = cur.fetchall()

            print(f"{'#':<3} {'ID':<4} {'Name':<14} {'GP':>6}")
            for i, r in enumerate(rows, start=1):
                print(f"{i:<3} {r['id']:<4} {r['name']:<14} {int(r['garage_power']):>6}")
            return

        # Existing team view: --team without list-active.
        if team_filter:
            # Team-list sorting without active_only: by GP or name, depending on sort_by.
            if sort_by == "name":
                q += " ORDER BY name COLLATE NOCASE"
            else:
                q += " ORDER BY garage_power DESC"
            cur.execute(q, params)
            rows = cur.fetchall()

            print(f"{'#':<3} {'ID':<4} {'Name':<20} {'Alias':<15} {'Leader':<6} {'ABS':<3}")
            print("-" * 80)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for i, r in enumerate(rows, start=1):
                abs_mark = "x" if r["away_until"] and r["away_until"] > now_str else ""
                print(f"{i:<3} {r['id']:<4} {r['name']:<20} {r['alias'] or '-':<15} {bool(r['is_leader']):<6} {abs_mark:<3}")
            print("-" * 80)
            return

        # Standard full view.
        if sort_by == "name":
            q += " ORDER BY name COLLATE NOCASE"
        else:
            q += " ORDER BY garage_power DESC"

        cur.execute(q, params)
        rows = cur.fetchall()

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
    """List all players with is_leader = 1, regardless of active state."""
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
    """Print 'BIRTHDAY_IDS: 12,45,78' for today as one line."""
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

# Legacy alias for old code.
def birthday_command():
    bday_today()

def bday_list(*, active_only=False, num=None):
    """List birthdays (ID, name, birthday, emoji), sorted by next occurrence."""
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

        # First/last match and match count via matchscore + match.start.
        match_count = 0
        first_match = last_match = None
        if r:
            cur.execute("""
                SELECT
                    COUNT(*) AS match_count,
                    MIN(substr(m.start, 1, 10)) AS first_match,
                    MAX(substr(m.start, 1, 10)) AS last_match
                FROM matchscore ms
                JOIN match m ON ms.match_id = m.id
                WHERE ms.player_id = ?
            """, (pid,))
            ms_row = cur.fetchone()
            if ms_row:
                match_count = ms_row["match_count"] or 0
                first_match = ms_row["first_match"]
                last_match = ms_row["last_match"]

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
    print(f"{'First Match':<15}: {first_match or '-'}")
    print(f"{'Last Match':<15}: {last_match or '-'}")
    print(f"{'Match Count':<15}: {match_count}")
    _print_wrapped("About", r['about'])
    _print_wrapped("Vehicles", r['preferred_vehicles'])
    _print_wrapped("Playstyle", r['playstyle'])
    _print_wrapped("Language", r['language'])
    _print_wrapped("Emoji", r['emoji'])

# =====================[ Mutations ]=======================

def add_player(name, alias=None, gp=0, active=True, birthday=None, team=None, discord_name=None):
    """
    - Alias is sanitized to [a-z0-9].
    - If no alias is provided, or it is empty for PLTE, generate it from the name with a unique 1..9 suffix.
    - Print the new ID after insert.
    """
    team = (team or "").upper().strip()
    if not is_valid_team(team):
        print("❌ Invalid team name. Allowed: PLTE or PL1–PL9")
        return

    # 1) Prepare/sanitize alias.
    alias = _sanitize_alias_token(alias) if alias else None
    alias_generated = False

    with db() as conn:
        cur = conn.cursor()

        # 2) Alias is required for PLTE; generate it automatically if missing.
        #    For other teams, alias remains optional and is not enforced globally.
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
                # Explicit alias: check whether it is exactly taken in PLTE.
                if _alias_exists(conn, alias, team_scope="PLTE"):
                    print(f"❌ Alias conflict in PLTE: '{alias}' already exists.")
                    return
        else:
            # Non-PLTE: sanitize; duplicates are allowed, but this would enforce global uniqueness:
            # if alias and _alias_exists(conn, alias, team_scope=None):
            #     print(f"❌ Alias conflict: '{alias}' already exists.")
            #     return
            pass

        # 3) Insert.
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
        print(USAGE_EDIT)
        return

    if args[0] == "--id":
        if len(args) < 2:
            print(USAGE_EDIT)
            return
        try:
            pid = int(args[1])
        except ValueError:
            print(USAGE_EDIT)
            return
        i = 2
    else:
        try:
            pid = int(args[0])
        except ValueError:
            print(USAGE_EDIT)
            return
        i = 1

    name = alias = birthday = team = discord = None
    gp = active = leader = None
    about = vehicles = playstyle = language = emoji = None

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
    # Resolve when provided via flags.
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
    print_command_help(
        usage="hcr2.py player <command> [options]",
        commands=[
            ("list [--sort gp|name] [--team TEAM]", "Show all players"),
            ("list-active [--sort gp|name] [--team TEAM]", "Show active players"),
            ("list-leader", "Show leaders only"),
            ("list-absent", "Show currently absent players"),
            ("bday today", "Print birthday IDs for today"),
            ("bday list [--active true|false] [--num N]", "List birthdays by next upcoming date"),
            ("add --team TEAM --name NAME [--alias ALIAS] [--gp GP] [--active true|false] [--birthday DD.MM.] [--discord NAME]", "Add one player"),
            ("edit --id <id> [--name NAME] [--alias ALIAS] [--gp GP] [--active true|false] [--birthday DD.MM.] [--team TEAM] [--discord NAME]", "Edit one player"),
            ("activate --id <id>", "Set one player active"),
            ("deactivate --id <id>", "Set one player inactive"),
            ("delete --id <id>", "Delete one player"),
            ("show --id ID | --name NAME | --discord NAME", "Show one player"),
            ("grep <term>", "Search by name, alias or Discord"),
            ("away (--id ID | --name NAME | --discord NAME) [--dur 1w|2w|3w|4w]", "Mark one player as away"),
            ("back (--id ID | --name NAME | --discord NAME)", "Clear away status for one player"),
        ],
        notes=[
            "edit also supports --leader, --about, --vehicles, --playstyle, --language and --emoji.",
            "Legacy positional aliases are still accepted for add, edit, activate, deactivate, delete, show, away and back.",
        ],
    )
