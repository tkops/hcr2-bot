#!/usr/bin/env python3
import asyncio
import discord
import re
import textwrap
import sys
import subprocess
import shlex  # für .p++ mit Anführungszeichen
from typing import Optional
from secrets_config import CONFIG, NEXTCLOUD_AUTH
from version import get_version, get_history

from discord.ext import tasks  # Scheduler
from zoneinfo import ZoneInfo   # Zeitzone Europe/Berlin
from datetime import time       # Uhrzeit für tasks.loop

# ===================== Konstante Limits & Regexe =============================

MAX_DISCORD_MSG_LEN = 1990
COLOR_SUCCESS = 0x2ECC71
COLOR_WARNING = 0xF1C40F
COLOR_ERROR = 0xE74C3C
COLOR_INFO = 0x3498DB

# Vorcompilierte Regexe für Parsing aus hcr2-Ausgaben
ID_LINE_RE = re.compile(r"^ID\s*:?\s*(\d+)", re.MULTILINE)
NAME_LINE_RE = re.compile(r"^Name\s*:?\s*(.+)$", re.MULTILINE)
BIRTHDAY_IDS_RE = re.compile(r"^BIRTHDAY_IDS:\s*([\d,\s]+)$", re.MULTILINE)
TEAM_RE = re.compile(r"^(PLTE|PL[1-9])$", re.IGNORECASE)

COMMANDS = {
    ".v": ["vehicle", "list"],
    ".p": ["player", "list"],
    ".m": ["match", "list"],
    ".h": None,
}

# Befehle, die auch normale User ausführen dürfen
PUBLIC_COMMANDS = [
    ".away", ".back", ".help",
    ".vehicles", ".about", ".language", ".playstyle", ".birthday", ".emoji",
    ".leader", ".profile",
    ".search", ".player", ".stats", ".d", ".donations", ".garagepower",
    ".km"
]

# ===================== Mode/Config laden ====================================

if len(sys.argv) != 2 or sys.argv[1] not in CONFIG:
    print("Usage: python3 bot.py [dev|prod]")
    sys.exit(1)

mode = sys.argv[1]
TOKEN = CONFIG[mode]["TOKEN"]
CHANNEL_IDS = CONFIG[mode]["CHANNEL_IDS"]               # User-Channel(s)
LEADER_ROLE_IDS = CONFIG[mode].get("LEADER_ROLE_IDS", [])
BIRTHDAY_CHANNEL_ID = CONFIG[mode].get("BIRTHDAY_CHANNEL_ID")
ADMIN_CHANNEL_IDS = CONFIG[mode].get("ADMIN_CHANNEL_IDS", [])  # Admin-Channel(s), separat

def validate_config():
    missing = []
    if not TOKEN:
        missing.append("TOKEN")
    if not isinstance(CHANNEL_IDS, (list, tuple)) or not CHANNEL_IDS:
        missing.append("CHANNEL_IDS")
    if not isinstance(ADMIN_CHANNEL_IDS, (list, tuple)):
        missing.append("ADMIN_CHANNEL_IDS")
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

class CliResult(str):
    """stdout of an hcr2 call. Behaves like the str it always was, plus `ok`,
    which mirrors the process exit code (see hcr2/output/status.py)."""

    ok: bool = True

    def __new__(cls, text: str, ok: bool = True):
        result = super().__new__(cls, text)
        result.ok = ok
        return result


def run_hcr2_sync(args):
    try:
        result = subprocess.run(
            ["python3", "hcr2.py"] + args,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        print(f"❌ Could not run: hcr2.py {' '.join(args)}")
        print(e)
        return None

    if result.returncode != 0 and not result.stdout.strip():
        # Crashed without a status line of its own - nothing useful to show.
        print(f"❌ Error while running: hcr2.py {' '.join(args)} (exit {result.returncode})")
        print(result.stderr)
        return None

    if result.stderr.strip():
        print(f"⚠️ stderr from: hcr2.py {' '.join(args)}")
        print(result.stderr)

    return CliResult(result.stdout, ok=result.returncode == 0)

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
        parts = desc.split("\n")
        first = True
        for part in parts:
            wrapped = tw.wrap(part) or [""]
            for i, seg in enumerate(wrapped):
                if first and i == 0:
                    lines.append(f"{cmd:<{left_col}} {seg}")
                else:
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
            week = val.replace("-", "/")
            return ["--name", name, "--week", week]
    return ["--name", " ".join(args)] if args else args

def parse_match_add_args(args):
    """
    Unterstützt:
      .m+ Opponent Name
      .m+ teamevent:12 Opponent Name
      .m+ season:59 start:2026-03-29 Opponent Name
      .m+ score:123000 scoreopp:121000 Opponent Name

    Alles mit key:value für bekannte Keys wird als optionales Feld interpretiert,
    der Rest wird als Opponent zusammengefügt.
    """
    flag_map = {
        "teamevent": "--teamevent",
        "season": "--season",
        "start": "--start",
        "score": "--score",
        "scoreopp": "--scoreopp",
    }

    cmd_args = ["match", "add"]
    opponent_parts = []

    for token in args:
        if ":" in token:
            key, value = token.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key in flag_map and value:
                cmd_args += [flag_map[key], value]
                continue
        opponent_parts.append(token)

    opponent = " ".join(opponent_parts).strip()
    if not opponent:
        return None

    cmd_args += ["--opponent", opponent]
    return cmd_args

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
        return "❌ I could not find your player profile. Ask a leader to set your Discord name in the players table."
    args = ["player", "edit", str(pid), flag, value]
    return await run_hcr2(args)

def _in_channels(message, ids):
    """True, wenn msg.channel oder dessen Parent (Thread) in ids ist."""
    if not ids:
        return False
    ch = message.channel
    if ch.id in ids:
        return True
    parent_id = getattr(ch, "parent_id", None)
    return parent_id in ids

# A full roster does not fit in one Discord message; splitting beats dropping it,
# but an unbounded split would spam the channel on a runaway output.
CODEBLOCK_MAX_MESSAGES = 4
CODEBLOCK_FENCE_LEN = 8


def codeblock_chunks(text: str, *, budget: int) -> list[str]:
    """Split on line boundaries so a table never breaks in the middle of a row."""
    chunks: list[str] = []
    current: list[str] = []
    length = 0

    for line in (text or "").split("\n"):
        while len(line) > budget:
            if current:
                chunks.append("\n".join(current))
                current, length = [], 0
            chunks.append(line[:budget])
            line = line[budget:]
        if current and length + len(line) + 1 > budget:
            chunks.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1

    if current:
        chunks.append("\n".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


def _unfence(text: str) -> str:
    body = text.strip()[3:-3]
    return body.split("\n", 1)[1] if body.startswith(("python", "text", "ansi")) else body


async def send_codeblock(channel, text: str):
    if not text:
        await send_warning(channel, "No data found or an error occurred.")
        return

    s = text.strip()
    prefenced = s.startswith("```") and s.endswith("```")

    if prefenced and len(s) <= MAX_DISCORD_MSG_LEN:
        await channel.send(s)
        return
    if not prefenced and len(text) + CODEBLOCK_FENCE_LEN <= MAX_DISCORD_MSG_LEN:
        await channel.send(f"```\n{text}```")
        return

    chunks = codeblock_chunks(
        _unfence(s) if prefenced else text,
        budget=MAX_DISCORD_MSG_LEN - CODEBLOCK_FENCE_LEN,
    )
    for chunk in chunks[:CODEBLOCK_MAX_MESSAGES]:
        await channel.send(f"```\n{chunk}\n```")
    if len(chunks) > CODEBLOCK_MAX_MESSAGES:
        await send_warning(
            channel,
            f"Output cut off after {CODEBLOCK_MAX_MESSAGES} messages - {len(chunks)} would be needed. "
            "Narrow it down with a filter.",
        )

def _clean_status_text(text: str) -> str:
    text = (text or "").strip()
    for prefix in ("✅", "⚠️", "⚠", "❌", "ℹ️", "ℹ", "🟢", "🟡", "🗑️", "🗑", "✏️", "✏", "🔁"):
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text

def _output_is_error(text) -> bool:
    """Prefer the CLI's exit code; fall back to its ❌ status prefix.

    Deliberately no substring search for words like "invalid" or "not found" -
    those appear in player names, opponents and notes and turned successful
    commands red.
    """
    ok = getattr(text, "ok", None)
    if ok is not None:
        return not ok
    return (text or "").strip().startswith("❌")

async def send_status(channel, title: str, description: str = "", *, color: int = COLOR_INFO):
    embed = discord.Embed(title=title, description=description or None, color=color)
    await channel.send(embed=embed)

async def send_success(channel, title: str, description: str = ""):
    await send_status(channel, title, description, color=COLOR_SUCCESS)

async def send_warning(channel, description: str, *, title: str = "Check input"):
    await send_status(channel, title, description, color=COLOR_WARNING)

async def send_error(channel, description: str, *, title: str = "Error"):
    await send_status(channel, title, description, color=COLOR_ERROR)

async def send_usage(channel, usage: str, *, example: Optional[str] = None, note: Optional[str] = None):
    description = f"`{usage}`"
    if example:
        description += f"\nExample: `{example}`"
    if note:
        description += f"\n{note}"
    await send_warning(channel, description, title="How to use this command")

async def send_cli_result(channel, output: str, *, success_title: str = "Done"):
    if not output:
        await send_warning(channel, "No data found or an error occurred.")
        return
    cleaned = _clean_status_text(output)
    if _output_is_error(output):
        await send_error(channel, cleaned or output.strip())
        return
    await send_success(channel, success_title, cleaned)

def _parse_show_fields(output: str) -> dict[str, str]:
    fields = {}
    current_key = None
    for line in (output or "").splitlines():
        if current_key and line.startswith(" "):
            continuation = line.strip()
            if continuation:
                fields[current_key] = f"{fields[current_key]} {continuation}".strip()
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key:
            fields[key] = value or "-"
            current_key = key
    return fields

async def send_player_profile(channel, output: str, *, title: str = "Player profile"):
    if not output:
        await send_warning(channel, "No player data found.")
        return
    if _output_is_error(output):
        await send_error(channel, _clean_status_text(output))
        return

    data = _parse_show_fields(output)
    if not data:
        await send_codeblock(channel, output)
        return

    name = data.get("Name", "Unknown player")
    player_id = data.get("ID", "-")
    embed = discord.Embed(title=f"{title}: {name}", color=COLOR_INFO)
    rows = [("ID", player_id)]
    for label in (
        "Alias",
        "Garage Power",
        "Team",
        "Birthday",
        "Discord",
        "Active",
        "Leader",
        "About",
        "Vehicles",
        "Playstyle",
        "Language",
        "Away until",
    ):
        value = data.get(label)
        if value and value != "-":
            rows.append((label, value))

    left_col = max(len(label) for label, _ in rows) + 2
    value_width = max(20, 58 - left_col)
    lines = []
    for label, value in rows:
        wrapped = textwrap.wrap(
            value,
            width=value_width,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
        lines.append(f"{label:<{left_col}} {wrapped[0]}")
        for line in wrapped[1:]:
            lines.append(f"{'':<{left_col}} {line}")

    description = "```" + "\n".join(lines)
    if len(description) > 4090:
        description = description[:4087].rstrip() + "..."
    embed.description = description + "```"

    await channel.send(embed=embed)

def help_field(rows, left_col=24):
    lines = [f"{cmd:<{left_col}} {desc}" for cmd, desc in rows]
    return "```" + "\n".join(lines) + "```"

async def send_public_help(channel):
    embed = discord.Embed(
        title="Public commands",
        description="Use these commands in the team channel.",
        color=COLOR_INFO,
    )
    embed.add_field(
        name="Profile",
        value=help_field([
            (".profile", "Show your profile"),
            (".garagepower <number>", "Update Garage Power"),
            (".birthday <DD.MM.>", "Set birthday"),
            (".emoji <emoji>", "Set personal emoji"),
            (".about <text>", "Set bio"),
            (".vehicles <text>", "Set preferred vehicles"),
            (".language <text>", "Set language"),
            (".playstyle <text>", "Set playstyle"),
        ]),
        inline=False,
    )
    embed.add_field(
        name="Away",
        value=help_field([
            (".away [1w..4w]", "Mark yourself absent"),
            (".back", "Clear absence"),
        ]),
        inline=False,
    )
    embed.add_field(
        name="Search & stats",
        value=help_field([
            (".leader", "Show leaders"),
            (".search <term>", "Search players"),
            (".player <id>", "Show player"),
            (".stats", "Current performance"),
            (".donations", "Donation index below 100"),
            (".km [<player>|weeks]", "Kilometres of the last week"),
        ]),
        inline=False,
    )
    await channel.send(embed=embed)

async def send_admin_help(channel):
    embed = discord.Embed(
        title="Admin commands",
        description="Lowercase commands list or edit. Uppercase commands show details.",
        color=COLOR_INFO,
    )
    embed.add_field(
        name="Players",
        value=help_field([
            (".p", "List active PLTE players"),
            (".P <id>", "Show player details"),
            (".p search <term>", "Search players"),
            (".p <id> key:value", "Edit player"),
            ('.p++ "<Name>" <team>', "Add player"),
            (".p+ <id>", "Activate player"),
            (".p- <id>", "Deactivate player"),
            (".pa <id> [1w..4w]", "Set player away"),
            (".pb <id>", "Clear player away"),
            (".pl bday", "List birthdays"),
            (".pl absent", "List absent players"),
            (".S <id>", "Show player stats"),
        ]),
        inline=False,
    )
    embed.add_field(
        name="Team Events",
        value=help_field([
            (".t", "List team events"),
            (".T <id>", "Show team event details"),
            (".t <id> key:value", "Edit team event"),
            (".t+ <name> [week]", "Add team event"),
        ]),
        inline=False,
    )
    embed.add_field(
        name="Matches",
        value=help_field([
            (".m", "List matches"),
            (".m <season>", "List matches in season"),
            (".M <id>", "Show match details"),
            (".m <id> key:value", "Edit match"),
            (".m+ <opponent>", "Add match"),
            (".m- <id>", "Delete match"),
        ]),
        inline=False,
    )
    embed.add_field(
        name="Scores",
        value=help_field([
            (".x", "List current scores"),
            (".x <matchid>", "List scores for match"),
            (".x <scoreid> <score> [p]", "Edit score"),
            (".x <scoreid> - <points>", "Edit points only"),
            (".xa <scoreid>", "Toggle absent"),
            (".x- <scoreid>", "Delete score"),
        ]),
        inline=False,
    )
    embed.add_field(
        name="Seasons",
        value=help_field([
            (".s", "List seasons"),
            (".s+ <division>", "Add next season"),
            (".s <num> [division]", "Add/edit season"),
        ]),
        inline=False,
    )
    embed.add_field(
        name="Sheets",
        value=help_field([
            (".c <matchid>", "Create match sheet"),
            (".i <matchid>", "Import match sheet"),
            (".pe", "Export player sheet"),
            (".pi", "Import player sheet"),
        ]),
        inline=False,
    )
    embed.add_field(
        name="Other",
        value=help_field([
            (".v", "List vehicles"),
            (".d", "Donation index below 100"),
            (".version", "Show bot version"),
            (".ph .th .sh .mh .xh", "Detailed admin helps"),
        ]),
        inline=False,
    )
    await channel.send(embed=embed)

# ===================== Birthday Scheduler ===================================

def _parse_birthday_ids(output: str):
    """
    Erwartet eine Zeile 'BIRTHDAY_IDS: 12,45,78' im Output von 'player bday today'.
    Gibt Liste von IDs (Strings) zurück.
    """
    if not output:
        return []
    m = BIRTHDAY_IDS_RE.search(output)
    if m:
        return [x.strip() for x in m.group(1).split(",") if x.strip().isdigit()]
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
    Holt IDs der Geburtstagskinder via 'player bday today',
    postet Glückwunsch + für jede ID ein 'player show <id>'.
    """
    if not BIRTHDAY_CHANNEL_ID:
        print("⚠️ BIRTHDAY_CHANNEL_ID not configured; skipping birthday post.")
        return

    channel = get_birthday_channel()
    if channel is None:
        print(f"⚠️ Could not resolve channel id {BIRTHDAY_CHANNEL_ID}")
        return

    out = await run_hcr2(["player", "bday", "today"])
    ids = _parse_birthday_ids(out)

    if not ids:
        print("ℹ️ No birthdays today.")
        return

    names = []
    profiles = []
    for pid in ids:
        show_out = await run_hcr2(["player", "show", pid])
        profiles.append(show_out or "")
        name = _parse_player_name_from_show(show_out) or f"ID {pid}"
        names.append(name)

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

    await channel.send(header)
    for p in profiles:
        if not p:
            continue
        await send_codeblock(channel, p)

# Zeitplan-Konstanten
SCHEDULE_TZ = ZoneInfo("Europe/Berlin")
SCHEDULE_TIME = time(hour=6, minute=30, tzinfo=SCHEDULE_TZ)

@tasks.loop(time=SCHEDULE_TIME)
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
    "Players (.p / .P / .pl) – Admin-Details",
    rows=[
        (".p",                   "List active PLTE Players."),
        (".P <id>",              "Show Player details."),
        (".p search <term>",     "Search Player by name/alias/discordname."),
        (".p <id> key:value",    "Edit Player\n"
                                 "keys: name, alias, gp, active, birthday, team, discord, "
                                 "about, vehicles, playstyle, language, leader, emoji."),
        (".pl bday",             "List birthdays sorted by next upcoming."),
        (".pl absent",           "List absent Ladys"),
        (".pa <id> [1w..4w]",    "Set Player to away. (absent=true)"),
        (".pb <id>",             "Set Player to back. (absent=false)"),
        (".pe ",                 "Export player table."),
        (".pi ",                 "Import player table and deletes sheet."),
        (".p+ id>",              "Reactivate Player."),
        (".p- <id>",             "Deactivate Player (verbose)."),
        ('.p++ "<Name>" <team> [alias] ', "Add Player team = PLTE | PL1..PL3. Alias is mandatory for PLTE Player. User only A-z and 0-9 letters for alias"),
    ],
    total_width=65,
    left_col=29,
)

HELP_TH = help_block(
    "Teamevents (.t / .T) – Admin-Details",
    rows=[
        (".t",                   "List last 10 teamevents"),
        (".T <id>",              "Show teamevent incl. vehicles."),
        (".t <id> key:value",    "Edit Teamevent\n"
                                 "keys: name, tracks, score, vehicles"),
        (".t+ <name> [week]",    "Add teamevent.\n"
                                 "If week is omitted, the next free ISO week is used."),
    ],
    total_width=65,
    left_col=22,
)

HELP_SH = help_block(
    "Seasons (.s) – Admin-Details",
    rows=[
        (".s",                   "List last 10 seasons."),
        (".s+ <div>",            "Add the next season.\n"
                                 "Only the division is required."),
        (".s <num> [div]",       "Legacy add or edit season."),
    ],
    total_width=65,
    left_col=22,
)

HELP_MH = help_block(
    "Matches (.m / .M) – Admin-Details",
    rows=[
        (".m",                   "List last 10 matches."),
        (".m <season>",          "List matches in one season."),
        (".M <id>",              "Show match details."),
        (".m <id> key:value",    "Edit match.\nkeys: teamevent, season, start, opponent, score, scoreopp"),
        (".m+ <opponent>",       "Add match with defaults."),
        (".m+ season:59 teamevent:12 start:2026-03-29 Gegner", "Add match with optional fields."),
        (".m- <match>",          "Delete match."),
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
        (".x- <matchscoreid>",         "Delete single matchscore."),
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

    # Channel-Routing (inkl. Threads => parent_id)
    in_user_channel = _in_channels(message, CHANNEL_IDS)
    in_admin_channel = _in_channels(message, ADMIN_CHANNEL_IDS)

    # Nur Nachrichten aus User- oder Admin-Channels zulassen
    if not (in_user_channel or in_admin_channel):
        return

    content = (message.content or "").strip()
    if not content.startswith("."):
        return

    parts = content.split()
    cmd = parts[0]
    args = parts[1:] if len(parts) > 0 else []

    leader = await is_leader(message.author)
    admin_cmd = not is_public(cmd)

    # Regelwerk:
    # - User-Channel: nur Public-Commands → Admin-Commands still ignorieren (auch für Leader).
    if in_user_channel and admin_cmd:
        return
    # - Admin-Channel: Admin-Commands nur für Leader.
    if in_admin_channel and admin_cmd and not leader:
        return
    # - Public-Commands: überall erlaubt.

    # ---- (Optional) Manuelles Triggern des Birthday-Posts (nur Leader) ----
    if cmd == ".birthday-now":
        if not leader:
            return
        await post_birthdays_now()
        return

    # ================== NEUE ADMIN-KOMMANDOS ==================

    if cmd == ".pl":
        if not args:
            await message.channel.send("Usage: .pl bday [--active true|false] [--num N] | .pl absent")
            return
        sub = args[0].lower()
        rest = args[1:]
        if sub == "bday":
            output = await run_hcr2(["player", "bday", "list"] + rest)
            await send_codeblock(message.channel, output)
            return
        if sub == "absent":
            output = await run_hcr2(["player", "list-absent"])
            await send_codeblock(message.channel, output)
            return
        await message.channel.send("Usage: .pl bday [--active true|false] [--num N] | .pl absent")
        return


    # --- Public: Update own Garage Power ---
    if cmd == ".garagepower":
        if len(args) != 1 or not args[0].isdigit():
            await send_usage(message.channel, ".garagepower <number>", example=".garagepower 123456")
            return

        discord_key = str(message.author)
        pid = await get_self_player_id(discord_key)
        if not pid:
            await send_error(
                message.channel,
                "I could not find your player profile. Ask a leader to set your Discord name in the players table.",
            )
            return

        output = await run_hcr2(["player", "edit", pid, "--gp", args[0]])
        await send_cli_result(message.channel, output, success_title="Garage Power updated")
        return


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

    # .p- <id>  → player deactivate <id> (verbose: ID, Name, Alias, GP)
    if cmd == ".p-":
        if len(args) != 1 or not args[0].isdigit():
            await message.channel.send("Usage: .p- <id>")
            return
        pid = args[0]

        # Vorher-Datensatz
        show_out = await run_hcr2(["player", "show", pid])
        id_m = ID_LINE_RE.search(show_out or "")
        name_m = NAME_LINE_RE.search(show_out or "")
        alias_m = re.search(r"^Alias\s*:?\s*(.+)$", show_out or "", re.MULTILINE)
        gp_m = re.search(r"^Garage Power\s*:?\s*(\d+)", show_out or "", re.MULTILINE)

        header = "ID | Name | Alias | GP"
        values = f"{id_m.group(1) if id_m else pid} | {name_m.group(1) if name_m else '-'} | {alias_m.group(1) if alias_m else '-'} | {gp_m.group(1) if gp_m else '-'}"

        await message.channel.send("**Player to deactivate:**\n```\n" + header + "\n" + values + "\n```")

        # Aktion
        result = await run_hcr2(["player", "deactivate", pid])
        await send_codeblock(message.channel, result or "n/a")
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

        call = ["player", "add", "--team", team, "--name", name]
        optional_flags = ["--alias", "--gp", "--active", "--birthday", "--discord"]
        for flag, value in zip(optional_flags, rest):
            call += [flag, value]
        output = await run_hcr2(call)
        await send_codeblock(message.channel, output)
        return

    # ================== ENDE NEUE ADMIN-KOMMANDOS ==================
    # --- Admin: Player stats (.S <id>) ---
    if cmd == ".S":
        if len(args) != 1 or not args[0].isdigit():
            await message.channel.send("Usage: .S <id>")
            return
        output = await run_hcr2(["stats", "player", args[0]])
        await send_codeblock(message.channel, output)
        return


    # --- Public: Leader-Liste ---
    if cmd == ".leader":
        output = await run_hcr2(["player", "list-leader"])
        await send_codeblock(message.channel, output)
        return

    # --- Public: Eigene Account-Infos anzeigen ---
    if cmd == ".profile":
        discord_key = str(message.author)
        output = await run_hcr2(["player", "show", "--discord", discord_key])
        await send_player_profile(message.channel, output, title="Your profile")
        return

    # --- Public: Player search ---
    if cmd == ".search":
        if not args:
            await send_usage(message.channel, ".search <term>", example=".search anna")
            return
        term = " ".join(args)
        output = await run_hcr2(["player", "grep", term])
        await send_codeblock(message.channel, output)
        return

    # --- Public: Show wie `.p <id>` ---
    if cmd == ".player":
        if len(args) != 1 or not args[0].isdigit():
            await send_usage(message.channel, f"{cmd} <id>", example=f"{cmd} 42")
            return
        output = await run_hcr2(["player", "show", args[0]])
        await send_player_profile(message.channel, output)
        return

    # --- Self profile updates (public): .vehicles / .about / .language / .playstyle / .birthday / .emoji ---
    if cmd in (".vehicles", ".about", ".language", ".playstyle", ".birthday", ".emoji"):
        if not args:
            usage = {
                ".vehicles": (".vehicles <text>", ".vehicles Rally Car, Muscle Car"),
                ".about": (".about <text>", ".about active daily, team events focused"),
                ".language": (".language <code or text>", ".language German / English"),
                ".playstyle": (".playstyle <text>", ".playstyle safe runs first"),
                ".birthday": (".birthday <DD.MM.>", ".birthday 15.07."),
                ".emoji": (".emoji <emoji>", ".emoji 🏁"),
            }[cmd]
            await send_usage(message.channel, usage[0], example=usage[1])
            return

        discord_key = str(message.author)

        if cmd == ".birthday":
            value = args[0].strip()
            if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.?", value):
                await send_usage(
                    message.channel,
                    ".birthday <DD.MM.>",
                    example=".birthday 15.07.",
                    note="Use day and month only, no year.",
                )
                return
            flag = "--birthday"
        elif cmd == ".emoji":
            value = args[0].strip()
            if not value or (" " in value):
                await send_usage(
                    message.channel,
                    ".emoji <emoji>",
                    example=".emoji 🏁",
                    note="Use one emoji only.",
                )
                return
            flag = "--emoji"
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
        titles = {
            ".vehicles": "Preferred vehicles updated",
            ".about": "About text updated",
            ".language": "Language updated",
            ".playstyle": "Playstyle updated",
            ".birthday": "Birthday updated",
            ".emoji": "Emoji updated",
        }
        await send_cli_result(message.channel, output, success_title=titles[cmd])
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
        await send_cli_result(message.channel, output, success_title="Away status updated")
        return

    if cmd == ".back":
        discord_key = str(message.author)
        output = await run_hcr2(["player", "back", "--discord", discord_key])
        await send_cli_result(message.channel, output, success_title="Welcome back")
        return

    # --- Player Commands ---
    if cmd == ".p":
        if not args:
            output = await run_hcr2(["player", "list-active", "--team", "PLTE"])
            await send_codeblock(message.channel, output)
            return

        if args[0].lower() in ("search", "find"):
            if len(args) < 2:
                await send_usage(message.channel, ".p search <term>", example=".p search anna")
                return
            term = " ".join(args[1:])
            output = await run_hcr2(["player", "grep", term])
            await send_codeblock(message.channel, output)
            return

        if args[0].isdigit():
            player_id = args[0]
            if len(args) == 1:
                await send_usage(
                    message.channel,
                    ".P <id>",
                    example=f".P {player_id}",
                    note="Uppercase commands show details. Lowercase .p lists or edits players.",
                )
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

        await send_usage(
            message.channel,
            ".p | .p search <term> | .p <id> key:value [...]",
            example=".p 42 gp:123456",
        )
        return

    # --- Sheet create ---
    if cmd == ".c" and len(args) == 1 and args[0].isdigit():
        output = await run_hcr2(["sheet", "create", args[0]])
        if output:
            lines = output.strip().splitlines()
            link = lines[-1] if lines and lines[-1].startswith("http") else None
            desc = f"Open file" if link else output
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
            desc = f"Open file\n\n" + "\n".join(l for l in lines if not l.startswith("http")) if link else output
            embed = discord.Embed(title="📥 Sheet import", description=desc, color=0x3498db)
            await message.channel.send(embed=embed)
        else:
            await message.channel.send("❌ Error during sheet import.")
        return

    # --- Sheet player export ---
    if cmd == ".pe":
        output = await run_hcr2(["sheet", "player", "export"])
        if output:
            lines = output.strip().splitlines()
            link = next((l for l in lines if l.startswith("http")), None)
            desc = f"Open file\n\n" + "\n".join(l for l in lines if not l.startswith("http")) if link else output
            embed = discord.Embed(title="📤 Player export", description=desc, color=0xf1c40f)
            await message.channel.send(embed=embed)
        else:
            await message.channel.send("❌ Error during player export.")
            return

    # --- Sheet player import ---
    if cmd == ".pi":
        output = await run_hcr2(["sheet", "player", "import"])
        if output:
            lines = output.strip().splitlines()
            link = next((l for l in lines if l.startswith("http")), None)
            desc = f"Open file\n\n" + "\n".join(l for l in lines if not l.startswith("http")) if link else output
            embed = discord.Embed(title="📥 Player import", description=desc, color=0x9b59b6)
            await message.channel.send(embed=embed)
        else:
            await message.channel.send("❌ Error during player import.")
        return


    # --- Stats ---
    if cmd == ".stats":
        # Default: perf
        sub = args[0].lower() if args else "perf"
        rest = args[1:] if args else []

        if sub in ("bday", "birthday"):
            call = ["stats", "bdayplot"] + rest

        elif sub == "perf":
            # .stats perf [season] [noskip]
            season = None
            noskip = False
            for a in rest:
                if a.lower() == "noskip":
                    noskip = True
                elif season is None and a.isdigit():
                    season = a

            call = ["stats", "perf"]
            if season:
                call.append(season)
            if noskip:
                call.append("--no-skip")

        elif sub == "score":
            # .stats score [season] [noskip]
            # Default: aktuelle Season, --skip (kein Flag nötig)
            season = None
            noskip = False
            for a in rest:
                if a.lower() == "noskip":
                    noskip = True
                elif season is None and a.isdigit():
                    season = a

            call = ["stats", "score"]
            if season:
                call.append(season)
            if noskip:
                call.append("--no-skip")

        elif sub == "points":
            # .stats points [season] [noskip]
            # Default: aktuelle Season, --skip (kein Flag nötig)
            season = None
            noskip = False
            for a in rest:
                if a.lower() == "noskip":
                    noskip = True
                elif season is None and a.isdigit():
                    season = a

            call = ["stats", "points"]
            if season:
                call.append(season)
            if noskip:
                call.append("--no-skip")

        elif sub == "te":
            call = ["stats", "te"] + (rest[:1] if rest else [])
        elif sub == "battle":
            if len(rest) != 2 or not rest[0].isdigit() or not rest[1].isdigit():
                await send_usage(message.channel, ".stats battle <id1> <id2>", example=".stats battle 12 34")
                return
            call = ["stats", "battle", rest[0], rest[1]]
        elif sub == "absent":
            call = ["stats", "absent"] + rest
        else:
            call = ["stats", sub] + rest

        output = await run_hcr2(call)
        await send_codeblock(message.channel, output)
        return

    # --- Weekly kilometres from the distance chest ---
    if cmd == ".km":
        if args and args[0].lower() in ("weeks", "wochen"):
            call = ["distance", "weeks"]
        elif args:
            call = ["distance", "show", "--player", " ".join(args)]
        else:
            call = ["distance", "list"]
        output = await run_hcr2(call)
        await send_codeblock(message.channel, output)
        return

    # --- Donations under index 100 (PLTE) ---
    if cmd in (".d", ".donations"):
        output = await run_hcr2(["donations", "under"])
        await send_codeblock(message.channel, output)
        return

    # --- Seasons ---
    if cmd == ".s":
        output = await run_hcr2(["season", "list"] if not args else ["season", "add"] + args)
        await send_codeblock(message.channel, output)
        return

    if cmd == ".s+":
        if not args:
            await message.channel.send("Usage: .s+ <division>")
            return
        output = await run_hcr2(["season", "add"] + args)
        await send_codeblock(message.channel, output)
        return

    # --- Player details ---
    if cmd == ".P":
        if len(args) != 1 or not args[0].isdigit():
            await send_usage(message.channel, ".P <id>", example=".P 42")
            return
        output = await run_hcr2(["player", "show", args[0]])
        await send_codeblock(message.channel, output)
        return

    # --- Matches ---
    if cmd == ".m+":
        parsed = parse_match_add_args(args)
        if not parsed:
            await message.channel.send(
                "Usage: .m+ <opponent>\n"
                "   or: .m+ teamevent:<id> season:<num> start:<YYYY-MM-DD> [score:<n>] [scoreopp:<n>] <opponent>"
            )
            return

        output = await run_hcr2(parsed)
        await send_codeblock(message.channel, output)
        return

    if cmd == ".m-":
        tokens = content.split()[1:]

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
            output = await run_hcr2(["match", "list"])
            await send_codeblock(message.channel, output)
            return

        if args[0].isdigit():
            mid = args[0]

            if len(args) == 1:
                output = await run_hcr2(["match", "list", mid])
                await send_codeblock(message.channel, output)
                return

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

            show_out = await run_hcr2(["match", "show", mid])
            await send_codeblock(message.channel, show_out)
            return

        await send_usage(
            message.channel,
            ".m | .m <season> | .m <id> key:value [...]",
            example=".m 62",
            note="Use `.M <id>` to show match details.",
        )
        return

    if cmd == ".M":
        if len(args) == 1 and args[0].isdigit():
            output = await run_hcr2(["match", "show", args[0]])
        else:
            await send_usage(message.channel, ".M <id>", example=".M 42")
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

    # --- Matchscore Delete (.x- <id>) ---
    if cmd == ".x-":
        if not leader:
            return
        if len(args) != 1 or not args[0].isdigit():
            await message.channel.send("Usage: .x- <matchscoreid>")
            return
        ms_id = args[0]
        output = await run_hcr2(["matchscore", "delete", ms_id])
        await send_codeblock(message.channel, output)
        return


    # --- Matchscores ---
    if cmd == ".x":
        if not args:
            output = await run_hcr2(["matchscore", "list-short"])
            await send_codeblock(message.channel, output)
            return

        match_id = args[0]
        if len(args) == 1:
            output = await run_hcr2(["matchscore", "list-short", "--match", match_id])
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
        msg = [f"📦 Current version: `{get_version()}`\n\n**Recent changes:**"]
        for v, d, c in get_history(10):
            msg.append(f"- `{v}` ({d}):\n{c}")
        await message.channel.send("\n".join(msg))
        return

    if cmd == ".t+":
        if not args:
            await message.channel.send("Usage: .t+ <name> [week]  (e.g. .t+ Teamcup 2025/38)\nDefault week: next free ISO week.")
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

    # --- Teamevent details ---
    if cmd == ".T":
        if len(args) != 1 or not args[0].isdigit():
            await send_usage(message.channel, ".T <id>", example=".T 12")
            return
        output = await run_hcr2(["teamevent", "show", args[0]])
        await send_codeblock(message.channel, output)
        return

    # --- Teamevents ---
    if cmd == ".t":
        if not args:
            output = await run_hcr2(["teamevent", "list"])
            await send_codeblock(message.channel, output)
            return

        if len(args) == 1 and args[0].isdigit():
            await send_usage(
                message.channel,
                ".T <id>",
                example=f".T {args[0]}",
                note="Uppercase commands show details. Lowercase .t lists or edits team events.",
            )
            return

        if args[0].isdigit() and len(args) > 1:
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

        await send_usage(
            message.channel,
            ".t | .t <id> key:value [...]",
            example=".t 12 tracks:4 score:15000",
            note="Use `.T <id>` to show team-event details.",
        )
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
        await send_admin_help(message.channel)
        return

    # --- User Help ---
    if cmd == ".help":
        await send_public_help(message.channel)
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
        output = await run_hcr2(
            ["matchscore", "add", "--match", match_id, "--player", player_name, "--score", score, "--points", points]
        )
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

# Guarded so the module can be imported (tests/test_bot_contract.py) without
# connecting to Discord - an unguarded import would start a second bot instance.
if __name__ == "__main__":
    client.run(TOKEN)
