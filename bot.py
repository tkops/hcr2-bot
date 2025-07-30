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

# Check mode argument
if len(sys.argv) != 2 or sys.argv[1] not in CONFIG:
    print("Usage: python3 bot.py [dev|prod]")
    sys.exit(1)

mode = sys.argv[1]
TOKEN = CONFIG[mode]["TOKEN"]
ALLOWED_CHANNEL_ID = CONFIG[mode]["CHANNEL_IDS"]

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents)

client = MyClient()

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


    if cmd == ".p":
        if not args:
            output = run_hcr2(["player", "list-active", "--team", "PLTE"])
            await respond(message, output)
            return

        if args[0].isdigit():
            player_id = args[0]

            # Nur ID → show
            if len(args) == 1:
                output = run_hcr2(["player", "show", player_id])
                await respond(message, output)
                return

            # ID + weitere Argumente → edit
            edit_args = ["player", "edit", player_id]
            for arg in args[1:]:
                if ":" not in arg:
                    continue  # ignoriert ungültige Argumente
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
                }
                if key in flag_map:
                    edit_args += [flag_map[key], value]

            output = run_hcr2(edit_args)
            await respond(message, output)
            return

        await message.channel.send("⚠️ Invalid .p format. Use `.p`, `.p <id>` or `.p <id> key:value [...]`")
        return

    if cmd == ".c" and len(args) == 1 and args[0].isdigit():
        output = run_hcr2(["sheet", "create", args[0]])
        if output:
            lines = output.strip().splitlines()
            link = lines[-1] if lines[-1].startswith("http") else None
            desc = f"[Open file]({link})" if link else output
            embed = discord.Embed(title="📄 Sheet created", description=desc, color=0x2ecc71)
            await message.channel.send(embed=embed)
        else:
            await message.channel.send("❌ Error during sheet creation.")
        return
    
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

    if cmd == ".s":
        full_args = ["stats", "avg"] + args
        output = run_hcr2(full_args)
        await respond(message, output)
        return

    if cmd == ".S":
        output = run_hcr2(["season", "list"] if not args else ["season", "add"] + args)
        await respond(message, output)
        return

    if cmd == ".P" and args:
        term = " ".join(args)
        output = run_hcr2(["player", "grep", term])
        await respond(message, output)
        return

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

    if cmd == ".x":
        if not args:
            await message.channel.send("Usage: .x <id> <score|-> [points]")
            return

        match_id = args[0]

        # Nur .x <id> → aktueller Score anzeigen
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

    if cmd in [".version"]:
        await message.channel.send(f"📦 Current version: `{get_version()}`")
        return


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

    if cmd == ".h":
        help_text = (
            "```text\n"
            "Players & Stats:\n"
            "  .p                  List active PLTE players\n"
            "  .p <id>             Show player details by ID\n"
            "  .p <id> k:v [...]   Edit player fields (name, alias, gp, ...)\n"
            "  .P <term>           Search player by name or alias\n"
            "  .s [season]         Show average stats (default: current season)\n\n"
            "Matches & Scores:\n"
            "  .m                  List recent matches\n"
            "  .m <id>             Show match details\n"
            "  .x <id>             Show scores for match\n"
            "  .x <id> <score> [p] Set score and optional points\n"
            "  .x <id> - <points>  Set only points (keep score)\n\n"
            "Sheets (Excel):\n"
            "  .c <id>             Create sheet and upload to Nextcloud\n"
            "  .i <id>             Import scores from Excel sheet\n\n"
            "Events & Seasons:\n"
            "  .t                  List all teamevents\n"
            "  .t <id>             Show teamevent and vehicles\n"
            "  .t add <name> <kw>  Add teamevent (e.g. 2025/38)\n"
            "  .S                  List last 10 seasons\n"
            "  .S <num> [div]      Add or update season\n\n"
            "Misc:\n"
            "  .a                  Show alias map for PLTE players\n"
            "  .v                  List all vehicles\n"
            "  .h                  Show this help message\n"
            "  .version            Show bot version\n"
            "```"
        )


        await message.channel.send(help_text)
        return

    if cmd in COMMANDS:
        base_cmd = COMMANDS[cmd]
        if base_cmd is None:
            return
        output = run_hcr2(base_cmd + args)
        await respond(message, output)
        return

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

async def respond(message, output):
    if not output:
        await message.channel.send("⚠️ No data found or error occurred.")
    elif len(output) <= MAX_DISCORD_MSG_LEN:
        await message.channel.send(f"```\n{output}```")
    else:
        await message.channel.send("⚠️ Output too long to display.")

client.run(TOKEN)

