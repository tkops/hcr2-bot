#!/usr/bin/env python3
import discord
import re
import sys
import subprocess
from secrets_config import CONFIG, NEXTCLOUD_AUTH
from version import get_version

MAX_DISCORD_MSG_LEN = 1990

COMMANDS = {
    ".a": ["stats", "alias"],
    ".v": ["vehicle", "list"],
    ".p": ["player", "list"],
    ".m": ["match", "list"],
    ".h": None,
}

# Befehle, die auch normale User ausführen dürfen
PUBLIC_COMMANDS = [".away", ".back", ".help", ".vehicles", ".about", ".language", ".playstyle"]

# Check mode argument
if len(sys.argv) != 2 or sys.argv[1] not in CONFIG:
    print("Usage: python3 bot.py [dev|prod]")
    sys.exit(1)

mode = sys.argv[1]
TOKEN = CONFIG[mode]["TOKEN"]
ALLOWED_CHANNEL_ID = CONFIG[mode]["CHANNEL_IDS"]
LEADER_ROLE_IDS = CONFIG[mode].get("LEADER_ROLE_IDS", [])

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        intents.guilds = True
        super().__init__(intents=intents)

client = MyClient()

# --- Helpers for hcr2.py ---
def run_hcr2(args):
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

def parse_teamevent_add_args(args):
    for i, val in enumerate(args):
        if re.match(r"^\d{4}[/\-]\d{1,2}$", val):
            name = " ".join(args[:i])
            rest = args[i:]
            return [name] + rest
    return args

async def is_leader(member: discord.Member) -> bool:
    return any(r.id in LEADER_ROLE_IDS for r in member.roles)

def get_self_player_id(discord_key: str):
    """
    Holt die Player-ID anhand des Discord-Namens über 'player show --discord'.
    Erwartet eine Ausgabezeile wie: 'ID             : 89'
    """
    out = run_hcr2(["player", "show", "--discord", discord_key])
    if not out:
        return None
    m = re.search(r"^ID\s*:?\s*(\d+)", out, flags=re.MULTILINE)
    if not m:
        return None
    return m.group(1)

def update_self_field(discord_key: str, flag: str, value: str):
    pid = get_self_player_id(discord_key)
    if not pid:
        return "❌ Could not resolve your player. Make sure your Discord is set in the players table."
    args = ["player", "edit", str(pid), flag, value]
    return run_hcr2(args)

# --- Message Handling ---
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

    # Standard: nur Leader dürfen Befehle ausführen, außer wenn in PUBLIC_COMMANDS
    if not leader and cmd not in PUBLIC_COMMANDS:
        return

    # --- Self profile updates (public): .vehicles / .about / .language / .playstyle ---
    if cmd in (".vehicles", ".about", ".language", ".playstyle"):
        if not args:
            usage = {
                ".vehicles": "Usage: .vehicles <text>",
                ".about": "Usage: .about <text>",
                ".language": "Usage: .language <code or text>",
                ".playstyle": "Usage: .playstyle <text>",
            }[cmd]
            await message.channel.send(usage)
            return

        value = " ".join(args).strip()
        discord_key = str(message.author)

        flag_map = {
            ".vehicles": "--vehicles",
            ".about": "--about",
            ".language": "--language",
            ".playstyle": "--playstyle",
        }
        output = update_self_field(discord_key, flag_map[cmd], value)
        await respond(message, output)
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
        output = run_hcr2(call)
        await respond(message, output)
        return

    if cmd == ".back":
        discord_key = str(message.author)
        output = run_hcr2(["player", "back", "--discord", discord_key])
        await respond(message, output)
        return

    # --- Player Commands ---
    if cmd == ".p":
        if not args:
            output = run_hcr2(["player", "list-active", "--team", "PLTE"])
            await respond(message, output)
            return

        if args[0].isdigit():
            player_id = args[0]
            if len(args) == 1:
                output = run_hcr2(["player", "show", player_id])
                await respond(message, output)
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

            output = run_hcr2(edit_args)
            await respond(message, output)
            return

        await message.channel.send("⚠️ Invalid .p format. Use `.p`, `.p <id>` or `.p <id> key:value [...]`")
        return

    # --- Sheet create ---
    if cmd == ".c" and len(args) == 1 and args[0].isdigit():
        output = run_hcr2(["sheet", "create", args[0]])
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
        output = run_hcr2(["sheet", "import", args[0]])
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
    if cmd == ".s":
        full_args = ["stats", "avg"] + args
        output = run_hcr2(full_args)
        await respond(message, output)
        return

    # --- Seasons ---
    if cmd == ".S":
        output = run_hcr2(["season", "list"] if not args else ["season", "add"] + args)
        await respond(message, output)
        return

    # --- Player search ---
    if cmd == ".P" and args:
        term = " ".join(args)
        output = run_hcr2(["player", "grep", term])
        await respond(message, output)
        return

    # --- Matches ---
    if cmd == ".m":
        if not args:
            output = run_hcr2(["match", "list"])
        elif len(args) == 1 and args[0].isdigit():
            output = run_hcr2(["match", "show", args[0]])
        else:
            await message.channel.send("⚠️ Invalid .m format. Use `.m` or `.m <id>`")
            return
        await respond(message, output)
        return

    # --- Matchscores ---
    if cmd == ".x":
        if not args:
            await message.channel.send("Usage: .x <id> <score|-> [points]")
            return

        match_id = args[0]
        if len(args) == 1:
            output = run_hcr2(["matchscore", "list", "--match", match_id])
            await respond(message, output)
            return

        score_arg = args[1]
        points_arg = args[2] if len(args) > 2 else None

        cmd_args = ["matchscore", "edit", match_id]
        if score_arg != "-":
            cmd_args += ["--score", score_arg]
        if points_arg:
            cmd_args += ["--points", points_arg]

        output = run_hcr2(cmd_args)
        await respond(message, output)
        return

    # --- Version ---
    if cmd == ".version":
        await message.channel.send(f"📦 Current version: `{get_version()}`")
        return

    # --- Teamevents ---
    if cmd == ".t":
        if not args:
            output = run_hcr2(["teamevent", "list"])
        elif args[0].lower() == "add":
            parsed_args = parse_teamevent_add_args(args[1:])
            output = run_hcr2(["teamevent", "add"] + parsed_args)
            if not output:
                await message.channel.send("⚠️ No data found or error occurred.")
            elif output.strip().startswith("Teamevent "):
                await message.channel.send("✅ Teamevent added:\n```\n" + output + "```")
            else:
                await message.channel.send("```\n" + output + "```")
            return
        elif len(args) == 1 and args[0].isdigit():
            output = run_hcr2(["teamevent", "show", args[0]])
        else:
            await message.channel.send("⚠️ Invalid .t format. Use `.t`, `.t <id>`, or `.t add ...`")
            return
        await respond(message, output)
        return

    # --- Admin Help ---
    if cmd == ".h":
        help_text = (
            "**Players & Stats:**"
            "```"
            " .p                  List active PLTE players\n"
            " .p <id>             Show player details by ID\n"
            " .p <id> k:v [...]   Edit player fields (name, alias, gp, ...)\n"
            " .P <term>           Search player by name or alias\n"
            " .s [season]         Show average stats (default: current season)\n"
            " .away [1w..4w]      Mark yourself absent for given weeks (default 1w)\n"
            " .back               Clear your absence\n"
            " .vehicles <text>    Set your preferred vehicles\n"
            " .about <text>       Set your about/bio text\n"
            " .language <text>    Set your language (e.g., en,de)\n"
            " .playstyle <text>   Set your playstyle\n"
            "```"
            "**Matches & Scores:**"
            "```"
            " .m                  List recent matches\n"
            " .m <id>             Show match details\n"
            " .x <id>             Show scores for match\n"
            " .x <id> <score> [p] Set score and optional points\n"
            " .x <id> - <points>  Set only points (keep score)\n"
            "```"
            "**Sheets (Excel):**"
            "```"
            " .c <id>             Create sheet and upload to Nextcloud\n"
            " .i <id>             Import scores from Excel sheet\n"
            "```"
            "**Events & Seasons:**"
            "```"
            " .t                  List all teamevents\n"
            " .t <id>             Show teamevent and vehicles\n"
            " .t add <name> <kw>  Add teamevent (e.g. 2025/38)\n"
            " .S                  List last 10 seasons\n"
            " .S <num> [div]      Add or update season\n"
            "```"
            "**Misc:**"
            "```"
            " .a                  Show alias map for PLTE players\n"
            " .v                  List all vehicles\n"
            " .h                  Show this help message\n"
            " .version            Show bot version\n"
            "```"
        )
        await message.channel.send(help_text)
        return

    # --- User Help ---
    if cmd == ".help":
        help_text = (
            "**Public Commands:**"
            "```"
            " .away [1w..4w]      Mark yourself absent for given weeks (default 1w)\n"
            " .back               Clear your absence\n"
            " .vehicles <text>    Set your preferred vehicles\n"
            " .about <text>       Set your about/bio text\n"
            " .language <text>    Set your language (e.g., en,de)\n"
            " .playstyle <text>   Set your playstyle\n"
            " .help               Show this help message\n"
            "```"
        )
        await message.channel.send(help_text)
        return

    # --- Aliases from COMMANDS map ---
    if cmd in COMMANDS:
        base_cmd = COMMANDS[cmd]
        if base_cmd is None:
            return
        output = run_hcr2(base_cmd + args)
        await respond(message, output)
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
        output = run_hcr2(["matchscore", "add", match_id, player_name, score, points])
        if not output or "✅" not in output:
            failed_lines.append(line)

    if failed_lines:
        await message.add_reaction("❗")
        await message.channel.send("❌ Failed to process the following lines:\n```" + "\n".join(failed_lines) + "```")
    elif lines and not failed_lines:
        await message.add_reaction("✅")

# --- Respond helper ---
async def respond(message, output):
    if not output:
        await message.channel.send("⚠️ No data found or error occurred.")
    elif len(output) <= MAX_DISCORD_MSG_LEN:
        await message.channel.send(f"```\n{output}```")
    else:
        await message.channel.send("⚠️ Output too long to display.")

client.run(TOKEN)

