from hcr2.output.players import (
    print_absent_players,
    print_away_cleared,
    print_away_set,
    print_add_player_result,
    print_edit_player_result,
    print_explicit_player_resolution_result,
    print_grep_result,
    print_active_requires_bool,
    print_birthday_ids,
    print_birthday_list,
    print_away_selector_required,
    print_gp_requires_integer,
    print_invalid_birthday_format,
    print_invalid_id,
    print_invalid_team_name,
    print_invalid_team_value,
    print_leader_requires_bool,
    print_name_required,
    print_no_matching_player,
    print_num_requires_integer,
    print_player_id_not_found,
    print_single_selector_required,
    print_value_error,
    print_player_detail,
    print_player_activated,
    print_player_deactivated,
    print_player_deleted,
    print_player_leaders,
    print_player_list,
    print_player_resolution_result,
)
from hcr2.output.deletions import print_delete_blocked, print_delete_not_found
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
    "Usage: player add <name> "
    "| [--team <team>] --name <name> [--alias <alias>] [--gp <gp>] [--active true|false] "
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
            print_num_requires_integer()
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
            print_invalid_id()
        return

    selectors = [x for x in (pid_flag, pname_flag, dname_flag) if x is not None]
    if len(selectors) == 0:
        print(USAGE_SHOW)
        return
    if len(selectors) > 1:
        print_single_selector_required()
        return

    pid = _resolve_player_id(player_id=pid_flag, player_name=pname_flag, discord_name=dname_flag)
    if pid is None:
        print_no_matching_player()
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

            if not name:
                print(USAGE_ADD)
                return

            team_raw = (team_token or "PLTE").upper()
            try:
                gp = int(gp_token) if gp_token is not None else 0
            except ValueError:
                print_gp_requires_integer()
                return
            active = parse_bool(active_token, default=True)
        else:
            if len(args) != 1:
                print(USAGE_ADD)
                return
            team_raw = "PLTE"
            name = args[0]
            alias = None
            gp = 0
            active = True
            birthday_raw = None
            discord_name = None

        if not name:
            print_name_required()
            return

        if not is_valid_team(team_raw):
            print_invalid_team_name()
            return

        birthday = parse_birthday(birthday_raw) if birthday_raw else None
        if birthday_raw and not birthday:
            print_invalid_birthday_format(birthday_raw)
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
    print_player_resolution_result(result, term, print_when_ambiguous=print_when_ambiguous)
    return None

def grep_players(term):
    rows = player_service.search_players(term)
    print_grep_result(term, rows)

def list_absent():
    print_absent_players(player_service.list_absent())


# =====================[ Lists & Display ]================

def show_players(active_only=False, sort_by="gp", team_filter=None):
    result = player_service.list_players(active_only=active_only, sort_by=sort_by, team_filter=team_filter)
    print_player_list(result, active_only=active_only, team_filter=team_filter)


def list_leaders():
    """List all players with is_leader = 1, regardless of active state."""
    print_player_leaders(player_service.list_leaders())


def bday_today():
    """Print 'BIRTHDAY_IDS: 12,45,78' for today as one line."""
    print_birthday_ids(player_service.birthday_ids_for_today())

# Legacy alias for old code.
def birthday_command():
    bday_today()

def bday_list(*, active_only=False, num=None):
    """List birthdays (ID, name, birthday, emoji), sorted by next occurrence."""
    result = player_service.list_birthdays(active_only=active_only, num=num)
    print_birthday_list(result)

def show_player(pid: int):
    r = player_service.get_player_detail(pid)

    if not r:
        print_player_id_not_found(pid)
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

    print_add_player_result(result, name)


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
                print_active_requires_bool(); return
            active = (val in ("true", "1"))
        elif args[i] == "--leader":
            i += 1
            val = args[i].lower()
            if val not in ("true", "false", "1", "0"):
                print_leader_requires_bool(); return
            leader = (val in ("true", "1"))
        elif args[i] == "--birthday":
            i += 1
            raw = args[i]; birthday = parse_birthday(raw)
            if not birthday:
                print_invalid_birthday_format(raw); return
        elif args[i] == "--team":
            i += 1
            team = args[i].upper()
            if not is_valid_team(team):
                print_invalid_team_value(team); return
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
    if print_edit_player_result(result, pid):
        show_player(pid)

def deactivate_player(pid):
    player_service.deactivate_player(pid)
    print_player_deactivated(pid)

def delete_player(pid):
    outcome = player_service.delete_player(pid)
    if outcome.status == "NOT_FOUND":
        print_delete_not_found(outcome)
        return
    if outcome.status == "BLOCKED":
        print_delete_blocked(outcome)
        return
    print_player_deleted(pid)

def activate_player(pid):
    player_service.activate_player(pid)
    print_player_activated(pid)

# =====================[ Away / Back ]======================
def _parse_weeks_token(token):
    """Accepts 1w..4w (optional 'w'); returns days 7..28. Default 1w."""
    return player_service.parse_weeks_token(token)

def _parse_weeks_token_or_default(token):
    try:
        return _parse_weeks_token(token)
    except ValueError as e:
        print_value_error(e)
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
        print_away_selector_required()
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
    print_explicit_player_resolution_result(result, player_name=player_name, discord_name=discord_name)
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
            ("add NAME | add [--team TEAM] --name NAME [--alias ALIAS] [--gp GP] [--active true|false] [--birthday DD.MM.] [--discord NAME]", "Add one player; TEAM defaults to PLTE"),
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
