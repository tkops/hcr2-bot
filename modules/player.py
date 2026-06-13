from hcr2.output.players import (
    format_birthday,
    print_absent_players,
    print_away_cleared,
    print_away_set,
    print_player_detail,
    print_player_leaders,
    print_player_list,
    print_player_search_rows,
)
from hcr2.services import players as player_service
from modules.common import (
    get_arg_value,
    is_help_request,
    parse_bool,
    print_command_help,
    print_unknown_command,
)

# =====================[ Configuration ]=====================
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
def parse_birthday(raw):
    return player_service.parse_birthday(raw)

def is_valid_team(team):
    return player_service.is_valid_team(team)

# =====================[ Unified Search ]===================
def search_players_like(term: str):
    """LIKE search over name/alias/discord, sorted by name (case-insensitive)."""
    return player_service.search_players(term)

def resolve_player_id_exact(term: str):
    """Resolve exactly: numeric ID or exact name/alias/discord (case-insensitive)."""
    return player_service.resolve_player_id_exact(term)

def resolve_player_id_fuzzy(term: str, *, print_when_ambiguous=True):
    """Try exact match first, then LIKE. Return ID if unique; otherwise print matches and return None."""
    result = player_service.resolve_player_id_fuzzy(term)
    if result.status == "FOUND":
        return result.player_id
    if result.status == "NOT_FOUND":
        print(f"❌ No players found matching '{term}'")
        return None

    if print_when_ambiguous:
        print(f"⚠️  Term '{term}' is not unique. Matching players:")
        print_player_search_rows(result.matches or [])
    return None

def grep_players(term):
    rows = player_service.search_players(term)
    if not rows:
        print(f"❌ No players found matching '{term}'")
        return
    print_player_search_rows(rows)

def list_absent():
    print_absent_players(player_service.list_absent())


# =====================[ Lists & Display ]================

def show_players(active_only=False, sort_by="gp", team_filter=None):
    result = player_service.list_players(active_only=active_only, sort_by=sort_by, team_filter=team_filter)
    print_player_list(result, active_only=active_only, team_filter=team_filter)


def list_leaders():
    """List all players with is_leader = 1, regardless of active state."""
    rows = player_service.list_leaders()
    if not rows:
        print("❌ No leaders found.")
        return
    print_player_leaders(rows)


def bday_today():
    """Print 'BIRTHDAY_IDS: 12,45,78' for today as one line."""
    ids = [str(player_id) for player_id in player_service.birthday_ids_for_today()]
    if ids:
        print("BIRTHDAY_IDS: " + ",".join(ids))

# Legacy alias for old code.
def birthday_command():
    bday_today()

def bday_list(*, active_only=False, num=None):
    """List birthdays (ID, name, birthday, emoji), sorted by next occurrence."""
    result = player_service.list_birthdays(active_only=active_only, num=num)
    items = result.rows

    print(f"{'ID':<4} {'Name':<20} {'Birthday':<10} {'Emoji'}")
    print("-" * 43)
    for du, r in items:
        print(f"{r.id:<4} {r.name:<20} {format_birthday(r.birthday):<10} {r.emoji}")
    print("-" * 43)
    scope = "(active only)" if active_only else "(all)"
    print(f"Count: {len(items)} {scope}")

def show_player(pid: int):
    r = player_service.get_player_detail(pid)

    if not r:
        print(f"❌ Player ID {pid} not found.")
        return

    print_player_detail(r)

# =====================[ Mutations ]=======================

def add_player(name, alias=None, gp=0, active=True, birthday=None, team=None, discord_name=None):
    """
    - Alias is sanitized to [a-z0-9].
    - If no alias is provided, or it is empty for PLTE, generate it from the name with a unique 1..9 suffix.
    - Print the new ID after insert.
    """
    result = player_service.add_player(
        name=name,
        alias=alias,
        gp=gp,
        active=active,
        birthday=birthday,
        team=team,
        discord_name=discord_name,
    )

    if result.status == "INVALID_TEAM":
        print("❌ Invalid team name. Allowed: PLTE or PL1–PL9")
        return
    if result.status == "ALIAS_GENERATION_FAILED":
        print(f"❌ Could not generate unique alias for base '{result.alias_base}' (1..9 all taken).")
        return
    if result.status == "ALIAS_CONFLICT":
        print(f"❌ Alias conflict in PLTE: '{result.alias}' already exists.")
        return

    alias_info = f" | Alias: {result.alias}" if result.alias else ""
    gen_info = " (generated)" if result.alias_generated else ""
    print(f"✅ Player '{name}' added. ID: {result.player_id}{alias_info}{gen_info} | Team: {result.team}")


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

    result = player_service.edit_player(
        pid,
        name=name,
        alias=alias,
        gp=gp,
        active=active,
        birthday=birthday,
        team=team,
        discord_name=discord,
        leader=leader,
        about=about,
        vehicles=vehicles,
        playstyle=playstyle,
        language=language,
        emoji=emoji,
    )
    if result.status == "NOT_FOUND":
        print(f"❌ Player ID {pid} not found.")
        return
    if result.status == "ALIAS_REQUIRED":
        print("❌ Alias is required for team PLTE.")
        return
    if result.status == "ALIAS_CONFLICT":
        print(f"❌ Alias conflict: '{result.alias}' vs '{result.conflict_alias}' (ID {result.conflict_player_id})")
        return
    if result.status == "NOTHING_TO_UPDATE":
        print("⚠️  Nothing to update.")
        return

    print(f"✅ Player {pid} updated.")
    show_player(pid)

def deactivate_player(pid):
    player_service.deactivate_player(pid)
    print(f"🟡 Player {pid} deactivated.")

def delete_player(pid):
    player_service.delete_player(pid)
    print(f"🗑️  Player {pid} deleted.")

def activate_player(pid):
    player_service.activate_player(pid)
    print(f"🟢 Player {pid} activated.")

# =====================[ Away / Back ]======================
def _parse_weeks_token(token):
    """Accepts 1w..4w (optional 'w'); returns days 7..28. Default 1w."""
    return player_service.parse_weeks_token(token)

def _parse_weeks_token_or_default(token):
    try:
        return _parse_weeks_token(token)
    except ValueError as e:
        print(f"❌ {e}")
        return None

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

    print_away_set(player_service.set_away_for_player(pid, days=days))

def away_clear_generic(player_id=None, player_name=None, discord_name=None):
    pid = _resolve_player_id(player_id, player_name, discord_name)
    if pid is None:
        return
    print_away_cleared(player_service.clear_away_for_player(pid))

def _resolve_player_id(player_id=None, player_name=None, discord_name=None):
    """Resolve a single player id from explicit flags."""
    result = player_service.resolve_player_id_explicit(
        player_id=player_id,
        player_name=player_name,
        discord_name=discord_name,
    )
    if result.status == "FOUND":
        return result.player_id
    if result.status == "INVALID_ID":
        print("❌ Invalid --id value")
    elif result.status == "DISCORD_NOT_FOUND":
        print(f"❌ No player found for discord_name='{discord_name}'")
    elif result.status == "DISCORD_AMBIGUOUS":
        _ = search_players_like(discord_name)
        print(f"⚠️ Multiple players match '{discord_name}'.")
    elif result.status == "NAME_AMBIGUOUS":
        _ = search_players_like(player_name)
        print(f"⚠️ Multiple players match '{player_name}'.")
    elif result.status == "NOT_FOUND":
        print(f"❌ No players found matching '{player_name}'")
    else:
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
