#!/usr/bin/env python3
import asyncio
import discord
import re
import textwrap
import sys
import subprocess
import shlex  # für .p++ mit Anführungszeichen
from secrets_config import CONFIG, NEXTCLOUD_AUTH
from version import get_version

from discord.ext import tasks  # Scheduler
from zoneinfo import ZoneInfo   # Zeitzone Europe/Berlin
from datetime import time       # Uhrzeit für tasks.loop

# ===================== Konstante Limits & Regexe =============================

MAX_DISCORD_MSG_LEN = 1990

# Vorcompilierte Regexe für Parsing aus hcr2-Ausgaben
ID_LINE_RE = re.compile(r"^ID\s*:?\s*(\d+)", re.MULTILINE)
NAME_LINE_RE = re.compile(r"^Name\s*:?\s*(.+)$", re.MULTILINE)
BIRTHDAY_IDS_RE = re.compile(r"^BIRTHDAY_IDS:\s*([\d,\s]+)$", re.MULTILINE)
TEAM_RE = re.compile(r"^(PLTE|PL[1-9])$", re.IGNORECASE)

COMMANDS = {
    ".a": ["stats", "alias"],
    ".v": ["vehicle", "list"],
    ".p": ["player", "list"],
    ".m": ["match", "list"],
    ".h": None,
}

# Befehle, die auch normale User ausführen dürfen
PUBLIC_COMMANDS = [
    ".away", ".back", ".help",
    ".vehicles", ".about", ".language", ".playstyle", ".birthday",
    ".leader", ".acc",
    ".search", ".show"
]

# ===================== Mode/Config laden ====================================

if len(sys.argv) != 2 or sys.argv[1] not in CONFIG:
    print("Usage: python3 bot.py [dev|prod]")
    sys.exit(1)

mode = sys.argv[1]
TOKEN = CONFIG[mode]["TOKEN"]
ALLOWED_CHANNEL_ID = CONFIG[mode]["CHANNEL_IDS"]
LEADER_ROLE_IDS = CONFIG[mode].get("LEADER_ROLE_IDS", [])
BIRTHDAY_CHANNEL_ID = CONFIG[mode].get("BIRTHDAY_CHANNEL_ID")

def validate_config():
    missing = []
    if not TOKEN:
        missing.append("TOKEN")
    if not isinstance(ALLOWED_CHANNEL_ID, (list, tuple)) or not ALLOWED_CHANNEL_ID:
        missing.append("CHANNEL_IDS")
    if missing:
        print(f"❌ Config error: missing/invalid {', '.join(missing)} for mode '{mode}'")
        sys.exit(1)

validate_config()

# ===================== Discord Client =======================================

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        intents.guilds = True
        super().__init__(intents=intents)

client = MyClient()

# ===================== hcr2 Helper (nicht-blockierend) ======================

def run_hcr2_sync(args):
    try:
        result = subprocess.run(
            ["python3", "hcr2.py"] + args,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"❌ Error while running: hcr2.py {' '.join(args)}")
        print(e)
        print(e.stderr)
        return None

async def run_hcr2(args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, run_hcr2_sync, args)

# ===================== 2-Spalten-Help-Builder ===============================

def help_block(title: str, rows, total_width=78, left_col=30):
    """
    rows: Liste von (command, description)
    """
    import textwrap

    right_width = max(10, total_width - left_col - 1)
    tw = textwrap.TextWrapper(
        width=right_width,
        expand_tabs=False,
        replace_whitespace=False,
        drop_whitespace=True,
        break_long_words=False,
        break_on_hyphens=False,
    )

    lines = [f"**{title}**", "```"]
    for cmd, desc in rows:
        # Manuelle Aufteilung an harten \n
        parts = desc.split("\n")
        first = True
        for part in parts:
            wrapped = tw.wrap(part) or [""]
            for i, seg in enumerate(wrapped):
                if first and i == 0:
                    # erste Zeile: Befehl + Text
                    lines.append(f"{cmd:<{left_col}} {seg}")
                else:
                    # Folgezeilen: nur rechtsbündig
                    pad = " " * left_col
                    lines.append(f"{pad} {seg}")
            first = False
    lines.append("```")
    return "\n".join(lines)
# ===================== Utilities ============================================

def parse_teamevent_add_args(args):
    for i, val in enumerate(args):
        if re.match(r"^\d{4}[/\-]\d{1,2}$", val):
            name = " ".join(args[:i])
            rest = args[i:]
            return [name] + rest
    return args

async def is_leader(member: discord.Member) -> bool:
    return any(r.id in LEADER_ROLE_IDS for r in member.roles)

async def get_self_player_id(discord_key: str):
    """
    Holt die Player-ID anhand des Discord-Namens über 'player show --discord'.
    Erwartet eine Ausgabezeile wie: 'ID             : 89'
    """
    out = await run_hcr2(["player", "show", "--discord", discord_key])
    if not out:
        return None
    m = ID_LINE_RE.search(out)
    if not m:
        return None
    return m.group(1)

async def update_self_field(discord_key: str, flag: str, value: str):
    pid = await get_self_player_id(discord_key)
    if not pid:
        return "❌ Could not resolve your player. Make sure your Discord is set in the players table."
    args = ["player", "edit", str(pid), flag, value]
    return await run_hcr2(args)

async def send_codeblock(channel, text: str):
    if not text:
        await channel.send("⚠️ No data found or error occurred.")
    elif len(text) <= MAX_DISCORD_MSG_LEN:
        await channel.send(f"```\n{text}```")
    else:
        await channel.send("⚠️ Output too long to display.")

# ===================== Birthday Scheduler ===================================

def _parse_birthday_ids(output: str):
    """
    Erwartet eine Zeile 'BIRTHDAY_IDS: 12,45,78' im Output von 'player birthday'.
    Gibt Liste von IDs (Strings) zurück.
    """
    if not output:
        return []
    m = BIRTHDAY_IDS_RE.search(output)
    if m:
        return [x.strip() for x in m.group(1).split(",") if x.strip().isdigit()]
    # Fallback: einzelne ID-Zeilen
    return re.findall(r"^\s*(\d+)\s*$", output, flags=re.MULTILINE)

def _parse_player_name_from_show(output: str):
    """
    Liest aus 'player show <id>' den Namen (Zeile 'Name : ...').
    """
    if not output:
        return None
    m = NAME_LINE_RE.search(output)
    return m.group(1).strip() if m else None

_bday_channel_cache = None
def get_birthday_channel():
    global _bday_channel_cache
    if _bday_channel_cache is None and BIRTHDAY_CHANNEL_ID:
        _bday_channel_cache = client.get_channel(BIRTHDAY_CHANNEL_ID)
    return _bday_channel_cache

async def post_birthdays_now():
    """
    Holt IDs der Geburtstagskinder via 'player birthday',
    postet Glückwunsch + für jede ID ein 'player show <id>'.
    """
    if not BIRTHDAY_CHANNEL_ID:
        print("⚠️ BIRTHDAY_CHANNEL_ID not configured; skipping birthday post.")
        return

    channel = get_birthday_channel()
    if channel is None:
        print(f"⚠️ Could not resolve channel id {BIRTHDAY_CHANNEL_ID}")
        return

    out = await run_hcr2(["player", "birthday"])
    ids = _parse_birthday_ids(out)

    if not ids:
        print("ℹ️ No birthdays today.")
        return

    # Namen einsammeln (für den Glückwunsch-Header)
    names = []
    profiles = []
    for pid in ids:
        show_out = await run_hcr2(["player", "show", pid])
        profiles.append(show_out or "")
        name = _parse_player_name_from_show(show_out) or f"ID {pid}"
        names.append(name)

    # Glückwunsch-Text bauen
    if len(names) == 1:
        header = (
            f"🎂 **Unser Geburtstagskind heute:** {names[0]}\n"
            f"Alles Gute zum neuen Lebensjahr! Viel Glück, Gesundheit und viele PBs! 🏁"
        )
    else:
        joined = ", ".join(names)
        header = (
            f"🎉 **Unsere heutigen Geburtstagskinder:** {joined}\n"
            f"Wir gratulieren euch herzlich zum neuen Lebensjahr – auf viele PBs und starken Runs! 🏁"
        )

    # Posten
    await channel.send(header)
    for p in profiles:
        if not p:
            continue
        await send_codeblock(channel, p)

# Zeitplan-Konstanten
SCHEDULE_TZ = ZoneInfo("Europe/Berlin")
SCHEDULE_TIME = time(hour=6, minute=30, tzinfo=SCHEDULE_TZ)

@tasks.loop(time=SCHEDULE_TIME)  # Läuft jeden Tag zur definierten Zeit
async def birthday_job():
    await post_birthdays_now()

@client.event
async def on_ready():
    if not birthday_job.is_running():
        birthday_job.start()
    hh = str(SCHEDULE_TIME.hour).zfill(2)
    mm = str(SCHEDULE_TIME.minute).zfill(2)
    print(f"✅ Logged in as {client.user} — birthday job scheduled for {hh}:{mm} Europe/Berlin.")

# ===================== MESSAGE HANDLING =====================================

def is_public(cmd: str) -> bool:
    return cmd in PUBLIC_COMMANDS

# ===================== Admin Sub-Help Texte (2 Spalten) ======================

HELP_PH = help_block(
    "Players (.p / .P) – Admin-Details",
    rows=[
        (".p",                   "List active PLTE Players."),
        (".p <id>",              "Show Player details."),
        (".p <id> key:value",    "Edit Player\n"
                                 "keys: name, alias, gp, active, birthday, team, discord, "
                                 "about, vehicles, playstyle, language, leader, emoji."),
        (".P <term>",            "Search for Player."),
        (".pa <id> [1w..4w]",    "Set Player to away. (absent=true)"),
        (".pb <id>",             "Set Player to back. (absent=false)"),
        (".p+ <id>",             "Reactivate Player."),
        (".p- <id>",             "Deactivate Player."),
        ('.p++ "<Name>" <team> [alias] ', "Add Player team = PLTE | PL1..PL3. Alias is mandatory for PLTE Player. User only A-z and 0-9 letters for alias"),
    ],
    total_width=65,
    left_col=29,
)

HELP_TH = help_block(
    "Teamevents (.t) – Admin-Details",
    rows=[
        (".t",                   "List last 10 teamevents"),
        (".t <id>",              "Show teamevent incl. vehicles."),
        (".t+ <name> <week>",    "Add teamevent (week-format: 2025/38 or 2025-38). "),
    ],
    total_width=65,
    left_col=22,
)

HELP_SH = help_block(
    "Seasons (.s) – Admin-Details",
    rows=[
        (".s",                   "List last 10 seasons."),
        (".s <num> [div]",       "Add or edit season (division optional). "),
    ],
    total_width=65,
    left_col=22,
)

HELP_MH = help_block(
    "Matches (.m) – Admin-Details",
    rows=[
        (".m",                   "List last 10 matches."),
        (".m <id>",              "Show match details."),
        (".m <id> key:value",    "Edit match.\nkeys: teamevent, season, start, opponent, score, scoreopp"),
        (".m+ <season> <event> <YYYY-MM-DD> <opponent>", "Add match."),
        (".m- <match>" ,         "Delete match."),
        (".M <match>",           "Show match details."),
    ],
    total_width=65,
    left_col=22,
)

HELP_XH = help_block(
    "Matchscores (.x) – Admin-Details",
    rows=[
        (".x  <matchid>",              "List scores for match <id>."),
        (".x  <matchid> <score> [p]",  "Set score  (points optional)."),
        (".x  <matchid> - <points>",   "Set points (score unchanged)."),
        (".xa <matchscoreid>",         "Toggle absent state for matchscore."),
    ],
    total_width=65,
    left_col=25,
)

# ===================== Events ===============================================

@client.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id not in ALLOWED_CHANNEL_ID:
        return

    content = message.content.strip()
    if not content.startswith("."):
        return

    parts = content.split()
    cmd = parts[0]
    args = parts[1:] if len(parts) > 0 else []

    leader = await is_leader(message.author)

    # nur Leader, außer Public-Commands
    if not leader and not is_public(cmd):
        return

    # ---- (Optional) Manuelles Triggern des Birthday-Posts (nur Leader) ----
    if cmd == ".birthday-now":
        if not leader:
            return
        await post_birthdays_now()
        return

    # ================== NEUE ADMIN-KOMMANDOS ==================

    # .pa <id> [1w..4w]  → player away --id <id> [--dur ...]
    if cmd == ".pa":
        if len(args) < 1 or not args[0].isdigit():
            await message.channel.send("Usage: .pa <id> [1w..4w]")
            return
        pid = args[0]
        dur = args[1] if len(args) > 1 and re.fullmatch(r"[1-4]\s*w?", args[1], flags=re.IGNORECASE) else None
        call = ["player", "away", "--id", pid]
        if dur:
            call += ["--dur", dur]
        output = await run_hcr2(call)
        await send_codeblock(message.channel, output)
        return

    # .pb <id>  → player back --id <id>
    if cmd == ".pb":
        if len(args) != 1 or not args[0].isdigit():
            await message.channel.send("Usage: .pb <id>")
            return
        output = await run_hcr2(["player", "back", "--id", args[0]])
        await send_codeblock(message.channel, output)
        return

    # .p+ <id>  → player activate <id>
    if cmd == ".p+":
        if len(args) != 1 or not args[0].isdigit():
            await message.channel.send("Usage: .p+ <id>")
            return
        output = await run_hcr2(["player", "activate", args[0]])
        await send_codeblock(message.channel, output)
        return

    # .p- <id>  → player deactivate <id>
    if cmd == ".p-":
        if len(args) != 1 or not args[0].isdigit():
            await message.channel.send("Usage: .p- <id>")
            return
        output = await run_hcr2(["player", "deactivate", args[0]])
        await send_codeblock(message.channel, output)
        return

    # .p++ "<Name>" <TEAM> [alias] [gp] [active] [birthday] [discord]
    # Name kann in Anführungszeichen stehen; TEAM kann vor ODER nach dem Namen kommen.
    if cmd == ".p++":
        raw = content[len(cmd):].strip()
        try:
            tokens = shlex.split(raw)
        except ValueError:
            await message.channel.send('Usage: .p++ "<Name>" <TEAM> [alias] [gp] [active] [birthday] [discord]')
            return
        if len(tokens) < 2:
            await message.channel.send('Usage: .p++ "<Name>" <TEAM> [alias] [gp] [active] [birthday] [discord]')
            return

        # Erkennen, ob erstes Token Team ist
        if TEAM_RE.match(tokens[0]):
            team = tokens[0].upper()
            name = tokens[1]
            rest = tokens[2:]
        else:
            name = tokens[0]
            if not TEAM_RE.match(tokens[1]):
                await message.channel.send('Usage: .p++ "<Name>" <TEAM> [alias] [gp] [active] [birthday] [discord]')
                return
            team = tokens[1].upper()
            rest = tokens[2:]

        call = ["player", "add", team, name] + rest
        output = await run_hcr2(call)
        await send_codeblock(message.channel, output)
        return

    # ================== ENDE NEUE ADMIN-KOMMANDOS ==================

    # --- Public: Leader-Liste ---
    if cmd == ".leader":
        output = await run_hcr2(["player", "list-leader"])
        await send_codeblock(message.channel, output)
        return

    # --- Public: Eigene Account-Infos anzeigen ---
    if cmd == ".acc":
        discord_key = str(message.author)
        output = await run_hcr2(["player", "show", "--discord", discord_key])
        await send_codeblock(message.channel, output)
        return

    # --- Public: Suche wie `.P <term>` ---
    if cmd == ".search":
        if not args:
            await message.channel.send("Usage: .search <term>")
            return
        term = " ".join(args)
        output = await run_hcr2(["player", "grep", term])
        await send_codeblock(message.channel, output)
        return

    # --- Public: Show wie `.p <id>` ---
    if cmd == ".show":
        if len(args) != 1 or not args[0].isdigit():
            await message.channel.send("Usage: .show <id>")
            return
        output = await run_hcr2(["player", "show", args[0]])
        await send_codeblock(message.channel, output)
        return

    # --- Self profile updates (public): .vehicles / .about / .language / .playstyle / .birthday ---
    if cmd in (".vehicles", ".about", ".language", ".playstyle", ".birthday"):
        if not args:
            usage = {
                ".vehicles": "Usage: .vehicles <text>",
                ".about": "Usage: .about <text>",
                ".language": "Usage: .language <code or text>",
                ".playstyle": "Usage: .playstyle <text>",
                ".birthday": "Usage: .birthday <DD.MM or DD.MM.>",
            }[cmd]
            await message.channel.send(usage)
            return

        discord_key = str(message.author)

        if cmd == ".birthday":
            value = args[0].strip()
            if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.?", value):
                await message.channel.send("⚠️ Invalid format. Use `DD.MM` or `DD.MM.` (no year).")
                return
            flag = "--birthday"
        else:
            value = " ".join(args).strip()
            flag_map = {
                ".vehicles": "--vehicles",
                ".about": "--about",
                ".language": "--language",
                ".playstyle": "--playstyle",
            }
            flag = flag_map[cmd]

        output = await update_self_field(discord_key, flag, value)
        await send_codeblock(message.channel, output)
        return

    # --- Away / Back ---
    if cmd == ".away":
        dur = None
        if args and re.fullmatch(r"[1-4]\s*w?", args[0], flags=re.IGNORECASE):
            dur = args[0]

        discord_key = str(message.author)
        call = ["player", "away", "--discord", discord_key]
        if dur:
            call += ["--dur", dur]
        output = await run_hcr2(call)
        await send_codeblock(message.channel, output)
        return

    if cmd == ".back":
        discord_key = str(message.author)
        output = await run_hcr2(["player", "back", "--discord", discord_key])
        await send_codeblock(message.channel, output)
        return

    # --- Player Commands ---
    if cmd == ".p":
        if not args:
            output = await run_hcr2(["player", "list-active", "--team", "PLTE"])
            await send_codeblock(message.channel, output)
            return

        if args[0].isdigit():
            player_id = args[0]
            if len(args) == 1:
                output = await run_hcr2(["player", "show", player_id])
                await send_codeblock(message.channel, output)
                return

            edit_args = ["player", "edit", player_id]
            for arg in args[1:]:
                if ":" not in arg:
                    continue
                key, value = arg.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                flag_map = {
                    "name": "--name",
                    "alias": "--alias",
                    "gp": "--gp",
                    "active": "--active",
                    "birthday": "--birthday",
                    "team": "--team",
                    "discord": "--discord",
                    "about": "--about",
                    "vehicles": "--vehicles",
                    "playstyle": "--playstyle",
                    "language": "--language",
                    "leader": "--leader",
                    "emoji": "--emoji",
                }
                if key in flag_map:
                    edit_args += [flag_map[key], value]

            output = await run_hcr2(edit_args)
            await send_codeblock(message.channel, output)
            return

        await message.channel.send("⚠️ Invalid .p format. Use `.p`, `.p <id>` or `.p <id> key:value [...]`")
        return

    # --- Sheet create ---
    if cmd == ".c" and len(args) == 1 and args[0].isdigit():
        output = await run_hcr2(["sheet", "create", args[0]])
        if output:
            lines = output.strip().splitlines()
            link = lines[-1] if lines and lines[-1].startswith("http") else None
            desc = f"[Open file]({link})" if link else output
            embed = discord.Embed(title="📄 Sheet created", description=desc, color=0x2ecc71)
            await message.channel.send(embed=embed)
        else:
            await message.channel.send("❌ Error during sheet creation.")
        return

    # --- Sheet import ---
    if cmd == ".i" and len(args) == 1 and args[0].isdigit():
        output = await run_hcr2(["sheet", "import", args[0]])
        if output:
            lines = output.strip().splitlines()
            link = next((l for l in lines if l.startswith("http")), None)
            desc = f"[Open file]({link})\n\n" + "\n".join(l for l in lines if not l.startswith("http")) if link else output
            embed = discord.Embed(title="📥 Sheet import", description=desc, color=0x3498db)
            await message.channel.send(embed=embed)
        else:
            await message.channel.send("❌ Error during sheet import.")
        return

    # --- Stats ---
    if cmd == ".stats":
        full_args = ["stats", "avg"] + args
        output = await run_hcr2(full_args)
        await send_codeblock(message.channel, output)
        return

    # --- Seasons ---
    if cmd == ".s":
        output = await run_hcr2(["season", "list"] if not args else ["season", "add"] + args)
        await send_codeblock(message.channel, output)
        return

    # --- Player search (Admin-Variante weiter nutzbar) ---
    if cmd == ".P" and args:
        term = " ".join(args)
        output = await run_hcr2(["player", "grep", term])
        await send_codeblock(message.channel, output)
        return

    # --- Matches ---
    if cmd == ".m+":
        tokens = content.split()[1:]  # alles nach dem .m+

        if len(tokens) < 4:
            await message.channel.send("Usage: .m+ <seasonid> <teameventid> <YYYY-MM-DD> <opponent>")
            return

        season_str, teamevent_str, date_str = tokens[0], tokens[1], tokens[2]
        opponent = " ".join(tokens[3:]).strip()

        if not season_str.isdigit() or not teamevent_str.isdigit():
            await message.channel.send("⚠️ seasonid und teameventid müssen Zahlen sein.")
            return

        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
            await message.channel.send("⚠️ Datum bitte als YYYY-MM-DD angeben.")
            return

        if not opponent:
            await message.channel.send("⚠️ Opponent fehlt.")
            return

        args = [
            "match", "add",
            "--teamevent", teamevent_str,
            "--season", season_str,
            "--start", date_str,
            "--opponent", opponent,
        ]
        output = await run_hcr2(args)
        await send_codeblock(message.channel, output)
        return

    if cmd == ".m-":
        tokens = content.split()[1:]  # alles nach dem .m-

        if len(tokens) != 1 or not tokens[0].isdigit():
            await message.channel.send("Usage: .m- <matchid>")
            return

        match_id = tokens[0]

        args = ["match", "delete", match_id]
        output = await run_hcr2(args)
        await send_codeblock(message.channel, output)
        return


    if cmd == ".m":
        if not args:
            # Liste (Standard)
            output = await run_hcr2(["match", "list"])
            await send_codeblock(message.channel, output)
            return

        # .m <id> [...]  -> list ODER edit
        if args[0].isdigit():
            mid = args[0]

            # Nur ID -> list
            if len(args) == 1:
                output = await run_hcr2(["match", "list", mid])
                await send_codeblock(message.channel, output)
                return

            # Edit: .m <id> key:value [...]
            flag_map = {
                "start":     "--start",
                "season":    "--season",
                "teamevent": "--teamevent",
                "opponent":  "--opponent",
                "score":     "--score",
                "scoreopp":  "--scoreopp",
            }
            edit_args = ["match", "edit", "--id", mid]
            for arg in args[1:]:
                if ":" not in arg:
                    continue
                key, value = arg.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                if key in flag_map and value:
                    edit_args += [flag_map[key], value]

            output = await run_hcr2(edit_args)
            await send_codeblock(message.channel, output)

            # Danach aktuellen Datensatz zeigen
            show_out = await run_hcr2(["match", "show", mid])
            await send_codeblock(message.channel, show_out)
            return

        await message.channel.send("⚠️ Invalid .m format. Use `.m`, `.m <id>`, or `.m <id> key:value [...]`")
        return


    if cmd == ".M":
        if len(args) == 1 and args[0].isdigit():
            output = await run_hcr2(["match", "show", args[0]])
        else:
            await message.channel.send("⚠️ Invalid .M format. Use `.M <id>`")
            return
        await send_codeblock(message.channel, output)
        return

    # --- Matchscore Absent toggle (.xa <score_id>) ---
    if cmd == ".xa":
        if not leader:
            return
        if len(args) != 1 or not args[0].isdigit():
            await message.channel.send("Usage: .xa <score_id>")
            return
        score_id = args[0]
        output = await run_hcr2(["matchscore", "edit", score_id, "--absent", "toggle"])
        await send_codeblock(message.channel, output)
        return


    # --- Matchscores ---
    if cmd == ".x":
        if not args:
            # Keine Argumente -> letztes Match anzeigen
            output = await run_hcr2(["matchscore", "list"])
            await send_codeblock(message.channel, output)
            return
    
        match_id = args[0]
        if len(args) == 1:
            # Nur ID -> Scores für dieses Match anzeigen
            output = await run_hcr2(["matchscore", "list", "--match", match_id])
            await send_codeblock(message.channel, output)
            return
    
        score_arg = args[1]
        points_arg = args[2] if len(args) > 2 else None
    
        cmd_args = ["matchscore", "edit", match_id]
        if score_arg != "-":
            cmd_args += ["--score", score_arg]
        if points_arg:
            cmd_args += ["--points", points_arg]
    
        output = await run_hcr2(cmd_args)
        await send_codeblock(message.channel, output)
        return


    # --- Version ---
    if cmd == ".version":
        await message.channel.send(f"📦 Current version: `{get_version()}`")
        return

    if cmd == ".t+":
        # Erwartet: .t+ <name> <kw>  (kw = 2025/38 oder 2025-38)
        if not args:
            await message.channel.send("Usage: .t+ <name> <kw>  (e.g. .t+ Teamcup 2025/38)")
            return
    
        parsed_args = parse_teamevent_add_args(args)
        output = await run_hcr2(["teamevent", "add"] + parsed_args)
        if not output:
            await message.channel.send("⚠️ No data found or error occurred.")
        elif output.strip().startswith("Teamevent "):
            await message.channel.send("✅ Teamevent added:\n```\n" + output + "```")
        else:
            await message.channel.send("```\n" + output + "```")
        return


    # --- Teamevents ---
    if cmd == ".t":
        if not args:
            # Liste aller Events
            output = await run_hcr2(["teamevent", "list"])
            await send_codeblock(message.channel, output)
            return
    
        if len(args) == 1 and args[0].isdigit():
            # Details eines Events anzeigen
            output = await run_hcr2(["teamevent", "show", args[0]])
            await send_codeblock(message.channel, output)
            return
    
        if args[0].isdigit() and len(args) > 1:
            # Editieren: .t <id> key:value ...
            event_id = args[0]
            edit_args = ["teamevent", "edit", event_id]
            flag_map = {
                "name": "--name",
                "tracks": "--tracks",
                "vehicles": "--vehicles",
                "score": "--score",
            }
            for arg in args[1:]:
                if ":" not in arg:
                    continue
                key, value = arg.split(":", 1)
                key = key.strip().lower()
                value = value.strip()
                if key in flag_map:
                    edit_args += [flag_map[key], value]
    
            output = await run_hcr2(edit_args)
            await send_codeblock(message.channel, output)

            show_out = await run_hcr2(["teamevent", "show", event_id])
            await send_codeblock(message.channel, show_out)

            return
    
        await message.channel.send("⚠️ Invalid .t format. Use `.t`, `.t <id>`, or `.t <id> key:value [...]`")
        return

    # --- Admin Sub-Helps (2 Spalten) ---
    if cmd == ".ph":
        if not leader:
            return
        await message.channel.send(HELP_PH)
        return

    if cmd == ".th":
        if not leader:
            return
        await message.channel.send(HELP_TH)
        return

    if cmd == ".sh":
        if not leader:
            return
        await message.channel.send(HELP_SH)
        return

    if cmd == ".mh":
        if not leader:
            return
        await message.channel.send(HELP_MH)
        return

    if cmd == ".xh":
        if not leader:
            return
        await message.channel.send(HELP_XH)
        return

    # --- Admin Help (Kurz) ---
    if cmd == ".h":
        help_text = help_block(
            "Administration (kurz) – Sub-Helps: .ph / .th / .sh / .mh / .xh",
            rows=[
                (".p[h]",        "Manage Players or show help."),
                (".P <t>",       "Search Player by name/alias/discordname."),
                (".s[h]",        "Manage seasons or show help."),
                (".t[h]",        "Manage teamevents or show help."),
                (".m[h]",        "Manage matches or show help."),
                (".x[h]",        "Manages scores or show help."),
                (".c <matchid>", "Create match sheet in nextcloud."),
                (".i <matchid>", "Import match sheet from nextcloud."),
                (".a",           "Alias-Map PLTE Team."),
                (".v",           "List vehicles."),
                (".s [s]",       "List matches in season [s] (default=current season)."),
                (".version",     "Show bot version."),
            ],
            total_width=68,
            left_col=22,
        )
        await message.channel.send(help_text)
        return

    # --- User Help ---
    if cmd == ".help":
        help_text = help_block(
            "Public Commands",
            rows=[
                (".away [1w..4w]",  "Mark yourself absent (default 1w)."),
                (".back",           "Clear your absence."),
                (".vehicles <t>",   "Set your preferred vehicles."),
                (".about <t>",      "Set your about/bio text."),
                (".language <t>",   "Set your language (e.g., german, english)."),
                (".playstyle <t>",  "Set your playstyle."),
                (".birthday DD.MM", "Set your birthday (no year)."),
                (".leader",         "Show all leaders."),
                (".acc",            "Show your account info."),
                (".search <term>",  "Search players."),
                (".show <id>",      "Show player by ID."),
                (".help",           "Show this help message."),
            ],
            total_width=68,
            left_col=22,
        )
        await message.channel.send(help_text)
        return

    # --- Aliases from COMMANDS map ---
    if cmd in COMMANDS:
        base_cmd = COMMANDS[cmd]
        if base_cmd is None:
            return
        output = await run_hcr2(base_cmd + args)
        await send_codeblock(message.channel, output)
        return

    # --- Fallback: matchscore import lines ---
    lines = content.splitlines()
    failed_lines = []

    for line in lines:
        parts = line.strip().split(";")
        if len(parts) != 4:
            failed_lines.append(line)
            continue
        match_id, player_name, score, points = map(str.strip, parts)
        output = await run_hcr2(["matchscore", "add", match_id, player_name, score, points])
        if not output or "✅" not in output:
            failed_lines.append(line)

    if failed_lines:
        await message.add_reaction("❗")
        await message.channel.send("❌ Failed to process the following lines:\n```" + "\n".join(failed_lines) + "```")
    elif lines and not failed_lines:
        await message.add_reaction("✅")

# ===================== Respond helper (deprecated) ===========================

async def respond(message, output):
    await send_codeblock(message.channel, output)

# ===================== Start =================================================

client.run(TOKEN)

