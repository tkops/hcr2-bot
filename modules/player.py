import sqlite3
import sys
import re
import textwrap
from datetime import datetime, timedelta

DB_PATH = "db/hcr2.db"

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

    elif cmd == "birthday":
        birthday_command()

    elif cmd == "show":
        # Flags unterstützen: --id / --name / --discord
        pid_flag = get_arg_value(args, "--id")
        pname_flag = get_arg_value(args, "--name")
        dname_flag = get_arg_value(args, "--discord")

        # Kurzform wie bisher: player show <id>
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

        add_player(name=name, alias=alias, gp=gp, active=active, birthday=birthday, team=team_raw, discord_name=discord_name)

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
        # Flags weiterhin unterstützen
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

        # bevorzugt Flags, sonst Kurzform
        dur = dur_flag or dur_pos
        if pid_flag or pname_flag or dname_flag:
            away_set_generic(player_id=pid_flag, player_name=pname_flag, discord_name=dname_flag, dur_token=dur)
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

# ----------------- helpers -----------------

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
    wrapper = textwrap.TextWrapper(width=width,
                                   subsequent_indent=" " * (indent + 2))
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
    return team == "PLTE" or re.fullmatch(r"PL[1-9]", team) is not None

def _today_mm_dd():
    return datetime.now().strftime("%m-%d")

# ----------------- list/show -----------------

def show_players(active_only=False, sort_by="gp", team_filter=None):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        q = """
            SELECT id, name, alias, garage_power, active, created_at,
                   birthday, team, discord_name, COALESCE(is_leader,0)
            FROM players
        """
        conditions = []
        if active_only:
            conditions.append("active = 1")
        if team_filter:
            conditions.append("UPPER(team) = ?")

        if conditions:
            q += " WHERE " + " AND ".join(conditions)

        if sort_by == "name":
            q += " ORDER BY name COLLATE NOCASE"
        else:
            q += " ORDER BY garage_power DESC"

        cur.execute(q, (team_filter,) if team_filter else ())
        rows = cur.fetchall()

        if team_filter:
            print(f"{'#':<3} {'ID':<4} {'Name':<20} {'Alias':<15} {'Leader':<6}")
            print("-" * 70)
            for i, (pid, name, alias, *_rest, is_leader) in enumerate(rows, start=1):
                print(f"{i:<3} {pid:<4} {name:<20} {alias or '-':<15} {bool(is_leader):<6}")
            print("-" * 70)
        else:
            cur.execute("SELECT COUNT(*) FROM players WHERE active = 1")
            active_count = cur.fetchone()[0]

            print(f"{'ID':<4} {'Name':<20} {'Alias':<15} {'GP':>6} {'Act':<5} {'Lead':<5} {'Birthday':<10} {'Team':<7} {'Discord':<18} {'Created'}")
            print("-" * 130)
            for row in rows:
                pid, name, alias, gp, active, created, birthday, team, discord_name, is_leader = row
                bday_fmt = format_birthday(birthday)
                print(f"{pid:<4} {name:<20} {alias or '':<15} {gp:>6} {str(bool(active)):>5} {str(bool(is_leader)):>5} {bday_fmt:<10} {team or '-':<7} {discord_name or '-':<18} {created}")
            print("-" * 130)
            print(f"🟢 Active players: {active_count}")

def list_leaders():
    """Listet alle Spieler mit is_leader = 1 (unabhängig von 'active')."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, COALESCE(discord_name, '-')
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
    for pid, name, discord_name in rows:
        print(f"{pid:<4} {name:<25} {discord_name:<30}")
    print("-" * 64)
    print(f"👑 Leaders: {len(rows)}")


def birthday_command():
    """Druckt NUR 'BIRTHDAY_IDS: 12,45,78' (eine Zeile) – keine weiteren Texte."""
    today = _today_mm_dd()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id
            FROM players
            WHERE birthday = ?
            ORDER BY name COLLATE NOCASE
        """, (today,))
        ids = [str(row[0]) for row in cur.fetchall()]

    if ids:
        print("BIRTHDAY_IDS: " + ",".join(ids))

def add_player(name, alias=None, gp=0, active=True, birthday=None, team=None, discord_name=None):
    alias = alias.strip() if alias else None

    if team == "PLTE":
        if not alias:
            print("❌ Alias is required for team PLTE.")
            return

        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, alias FROM players
                WHERE team = 'PLTE'
            """)
            for pid, existing_alias in cur.fetchall():
                if alias in existing_alias or existing_alias in alias:
                    print(f"❌ Alias conflict: '{alias}' vs '{existing_alias}' (ID {pid})")
                    return

            cur.execute(
                """
                INSERT INTO players (name, alias, garage_power, active, birthday, team, discord_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, alias, gp, int(active), birthday, team, discord_name)
            )
    else:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO players (name, alias, garage_power, active, birthday, team, discord_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, alias, gp, int(active), birthday, team, discord_name)
            )
    print(f"✅ Player '{name}' added.")

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
            i += 1
            name = args[i]
        elif args[i] == "--alias":
            i += 1
            alias = args[i]
        elif args[i] == "--gp":
            i += 1
            gp = int(args[i])
        elif args[i] == "--active":
            i += 1
            val = args[i].lower()
            if val not in ("true", "false", "1", "0"):
                print("❌ --active expects true|false")
                return
            active = (val in ("true", "1"))
        elif args[i] == "--leader":
            i += 1
            val = args[i].lower()
            if val not in ("true", "false", "1", "0"):
                print("❌ --leader expects true|false")
                return
            leader = (val in ("true", "1"))
        elif args[i] == "--birthday":
            i += 1
            raw = args[i]
            birthday = parse_birthday(raw)
            if not birthday:
                print(f"❌ Invalid birthday format: {raw} (use DD.MM.)")
                return
        elif args[i] == "--team":
            i += 1
            team = args[i].upper()
            if not is_valid_team(team):
                print(f"❌ Invalid team name: {team} (allowed: PLTE or PL1–PL9)")
                return
        elif args[i] == "--discord":
            i += 1
            discord = args[i]
        elif args[i] == "--about":
            i += 1
            about = args[i]
        elif args[i] == "--vehicles":
            i += 1
            vehicles = args[i]
        elif args[i] == "--playstyle":
            i += 1
            playstyle = args[i]
        elif args[i] == "--language":
            i += 1
            language = args[i]
        elif args[i] == "--emoji":
            i += 1
            emoji = args[i]
        i += 1

    if alias is not None:
        alias = alias.strip()

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        cur.execute("SELECT team, alias FROM players WHERE id = ?", (pid,))
        row = cur.fetchone()
        if not row:
            print(f"❌ Player ID {pid} not found.")
            return
        current_team, current_alias = row
        target_team = team or current_team
        target_alias = alias if alias is not None else current_alias

        if target_team == "PLTE":
            if not target_alias:
                print("❌ Alias is required for team PLTE.")
                return
            cur.execute("""
                SELECT id, alias FROM players
                WHERE team = 'PLTE' AND id != ?
            """, (pid,))
            for cid, calias in cur.fetchall():
                if target_alias in calias or calias in target_alias:
                    print(f"❌ Alias conflict: '{target_alias}' vs '{calias}' (ID {cid})")
                    return

        fields = []
        values = []

        if name:
            fields.append("name = ?")
            values.append(name)
        if alias is not None:
            fields.append("alias = ?")
            values.append(alias)
        if gp is not None:
            fields.append("garage_power = ?")
            values.append(gp)
        if active is not None:
            fields.append("active = ?")
            values.append(1 if active else 0)
        if birthday is not None:
            fields.append("birthday = ?")
            values.append(birthday)
        if team is not None:
            fields.append("team = ?")
            values.append(team)
        if discord is not None:
            fields.append("discord_name = ?")
            values.append(discord)
        if leader is not None:
            fields.append("is_leader = ?")
            values.append(1 if leader else 0)
        if about is not None:
            fields.append("about = ?")
            values.append(about)
        if vehicles is not None:
            fields.append("preferred_vehicles = ?")
            values.append(vehicles)
        if playstyle is not None:
            fields.append("playstyle = ?")
            values.append(playstyle)
        if language is not None:
            fields.append("language = ?")
            values.append(language)
        if emoji is not None:
            fields.append("emoji = ?")
            values.append(emoji)

        if not fields:
            print("⚠️  Nothing to update.")
            return

        values.append(pid)
        query = f"UPDATE players SET {', '.join(fields)} WHERE id = ?"
        conn.execute(query, values)

    print(f"✅ Player {pid} updated.")
    show_player(pid)

def deactivate_player(pid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE players SET active = 0 WHERE id = ?", (pid,))
    print(f"🟡 Player {pid} deactivated.")

def delete_player(pid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM players WHERE id = ?", (pid,))
    print(f"🗑️  Player {pid} deleted.")

def grep_players(term):
    pattern = f"%{term.lower()}%"
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, alias, garage_power, active, COALESCE(discord_name, '')
            FROM players
            WHERE LOWER(name) LIKE ? OR LOWER(alias) LIKE ?
               OR LOWER(COALESCE(discord_name, '')) LIKE ?
            ORDER BY name COLLATE NOCASE
        """, (pattern, pattern, pattern))
        rows = cur.fetchall()

    if not rows:
        print(f"❌ No players found matching '{term}'")
        return

    print(f"{'ID':<4} {'NAME':<20} {'Alias':<15} {'Discord':<22} {'GP':>5} {'Act':>5}")
    print("-" * 74)
    for pid, name, alias, gp, active, discord in rows:
        print(f"{pid:<4} {name:<20} {alias or '':<15} {discord or '':<22} {gp:>5} {str(bool(active))[:1]}")
    print("-" * 74)

def activate_player(pid):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE players SET active = 1 WHERE id = ?", (pid,))
    print(f"🟢 Player {pid} activated.")

def print_help():
    print("Usage: python hcr2.py player <command> [args]")
    print("\nAvailable commands:")
    print("  list [--sort gp|name] [--team TEAM]         Show all players")
    print("  list-active [--sort gp|name] [--team TEAM]  Show only active players")
    print("  list-leader                                 Show only leaders (id, name, discord)")
    print("  birthday                                    Congratulate today's birthdays and show profiles")
    print("  add <team> <name> [alias] [gp] [active] [birthday: dd.mm.] [discord_name]")
    print("  edit <id> --gp 90000 --team PL3 --birthday 15.07. --discord foo#1234 --leader true|false "
          "--about '...' --vehicles '...' --playstyle '...' --language 'en' --emoji '🚗'")
    print("  deactivate <id>               Set player inactive")
    print("  delete <id>                   Remove player")
    print("  show <id> | (--id ID | --name NAME | --discord NAME)")
    print("  grep <term>                   Search players by name/alias/discord (case-insensitive)")
    print("  activate <id>                 Set player active")
    print("  away (<term> [1w|2w|3w|4w]) | (--id ID | --name NAME | --discord NAME) [--dur 1w|2w|3w|4w]")
    print("  back <term> | (--id ID | --name NAME | --discord NAME)")

def show_player(pid):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, alias, garage_power, active, birthday, team, discord_name,
                   created_at, last_modified, active_modified, away_from, away_until,
                   COALESCE(is_leader, 0),
                   about, preferred_vehicles, playstyle, language, emoji
            FROM players
            WHERE id = ?
        """, (pid,))
        row = cur.fetchone()

        if not row:
            print(f"❌ Player ID {pid} not found.")
            return

        (id, name, alias, gp, active, birthday, team, discord,
         created, last_modified, active_modified, away_from, away_until, is_leader,
         about, preferred_vehicles, playstyle, language, emoji) = row

        print(f"{'ID':<15}: {id}")
        print(f"{'Name':<15}: {name}")
        print(f"{'Alias':<15}: {alias or '-'}")
        print(f"{'Garage Power':<15}: {gp}")
        print(f"{'Active':<15}: {bool(active)}")
        print(f"{'Leader':<15}: {bool(is_leader)}")
        print(f"{'Birthday':<15}: {format_birthday(birthday)}")
        print(f"{'Team':<15}: {team or '-'}")
        print(f"{'Discord':<15}: {discord or '-'}")
        print(f"{'Created':<15}: {created}")
        print(f"{'Last modified':<15}: {last_modified or '-'}")
        print(f"{'Active modified':<15}: {active_modified or '-'}")
        print(f"{'Away from':<15}: {away_from or '-'}")
        print(f"{'Away until':<15}: {away_until or '-'}")

        _print_wrapped("About", about)
        _print_wrapped("Vehicles", preferred_vehicles)
        _print_wrapped("Playstyle", playstyle)
        _print_wrapped("Language", language)
        _print_wrapped("Emoji", emoji)

# -------------- away/back core --------------

def _parse_weeks_token(token):
    """Accepts 1w..4w (optional 'w'); returns days 7..28. Default 1w."""
    if not token:
        return 7
    m = re.fullmatch(r"\s*([1-4])\s*w?\s*", token, flags=re.IGNORECASE)
    if not m:
        raise ValueError("Use 1w, 2w, 3w or 4w.")
    return int(m.group(1)) * 7

def _resolve_player_id_exact(term):
    """Versucht exakte Auflösung: ID, exakter Name/Alias/Discord (case-insensitive)."""
    # ID?
    if term.isdigit():
        pid = int(term)
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM players WHERE id = ?", (pid,))
            if cur.fetchone():
                return pid
            print(f"❌ No player with id {pid}")
            return None

    # exakte Felder (case-insensitive)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM players
            WHERE LOWER(name) = LOWER(?)
               OR LOWER(alias) = LOWER(?)
               OR LOWER(COALESCE(discord_name,'')) = LOWER(?)
        """, (term, term, term))
        rows = cur.fetchall()

    if len(rows) == 1:
        return rows[0][0]
    elif len(rows) > 1:
        _print_duplicates_for_term(term)
        return None
    else:
        return None  # kein Treffer

def _resolve_player_id_like(term):
    """Fallback mit LIKE (wie grep, aber inkl. discord_name). Eindeutig? → ID, sonst Liste."""
    pattern = f"%{term.lower()}%"
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, alias, garage_power, active, COALESCE(discord_name,'')
            FROM players
            WHERE LOWER(name) LIKE ?
               OR LOWER(alias) LIKE ?
               OR LOWER(COALESCE(discord_name,'')) LIKE ?
            ORDER BY name COLLATE NOCASE
        """, (pattern, pattern, pattern))
        rows = cur.fetchall()

    if len(rows) == 0:
        print(f"❌ No players found matching '{term}'")
        return None
    if len(rows) == 1:
        return rows[0][0]

    print(f"⚠️  Term '{term}' is not unique. Matching players:")
    print(f"{'ID':<4} {'NAME':<20} {'Alias':<15} {'Discord':<22} {'GP':>5} {'Act':>5}")
    print("-" * 74)
    for pid, name, alias, gp, active, discord in rows:
        print(f"{pid:<4} {name:<20} {alias or '':<15} {discord or '':<22} {gp:>5} {str(bool(active))[:1]}")
    print("-" * 74)
    return None

def _print_duplicates_for_term(term):
    pattern = f"%{term.lower()}%"
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, alias, garage_power, active, COALESCE(discord_name,'')
            FROM players
            WHERE LOWER(name) LIKE ?
               OR LOWER(alias) LIKE ?
               OR LOWER(COALESCE(discord_name,'')) LIKE ?
            ORDER BY name COLLATE NOCASE
        """, (pattern, pattern, pattern))
        rows = cur.fetchall()

    if not rows:
        print(f"❌ No players found matching '{term}'")
        return

    print(f"⚠️  Multiple players match '{term}':")
    print(f"{'ID':<4} {'NAME':<20} {'Alias':<15} {'Discord':<22} {'GP':>5} {'Act':>5}")
    print("-" * 74)
    for pid, name, alias, gp, active, discord in rows:
        print(f"{pid:<4} {name:<20} {alias or '':<15} {discord or '':<22} {gp:>5} {str(bool(active))[:1]}")
    print("-" * 74)

def away_set_fuzzy(term, dur_token):
    pid = _resolve_player_id_exact(term)
    if pid is None:
        pid = _resolve_player_id_like(term)
        if pid is None:
            return
    away_set_generic(player_id=str(pid), player_name=None, discord_name=None, dur_token=dur_token)

def away_clear_fuzzy(term):
    pid = _resolve_player_id_exact(term)
    if pid is None:
        pid = _resolve_player_id_like(term)
        if pid is None:
            return
    away_clear_generic(player_id=str(pid), player_name=None, discord_name=None)

def _parse_weeks_token_or_default(token):
    try:
        return _parse_weeks_token(token)
    except ValueError as e:
        print(f"❌ {e}")
        return None

def _fetch_player_brief(pid: int):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, alias, discord_name
            FROM players
            WHERE id = ?
        """, (pid,))
        return cur.fetchone()  # (id, name, alias, discord) oder None

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

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE players
               SET away_from = ?, away_until = ?
             WHERE id = ?
        """, (away_from, away_until, pid))

    brief = _fetch_player_brief(pid)
    if brief:
        _id, name, alias, discord = brief
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            UPDATE players
               SET away_from = NULL, away_until = NULL
             WHERE id = ?
        """, (pid,))

    brief = _fetch_player_brief(pid)
    if brief:
        _id, name, alias, discord = brief
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
        with sqlite3.connect(DB_PATH) as conn:
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
            _print_duplicates_for_term(discord_name)
            return None
        return rows[0][0]

    if player_name:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id FROM players
                WHERE LOWER(name) = LOWER(?)
            """, (player_name.strip(),))
            rows = cur.fetchall()
        if not rows:
            return _resolve_player_id_like(player_name)
        if len(rows) > 1:
            _print_duplicates_for_term(player_name)
            return None
        return rows[0][0]

    print("❌ Provide one of --id, --name, or --discord")
    return None

