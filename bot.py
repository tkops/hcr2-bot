import discord
import re
import sys
import subprocess
from secrets_config import CONFIG, NEXTCLOUD_AUTH

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

    if cmd == ".p" and len(args) == 1 and args[0].isdigit():
        output = run_hcr2(["player", "show", args[0]])
        await respond(message, output)
        return

    if cmd == ".p" and not args:
        output = run_hcr2(["player", "list-active", "--team", "PLTE"])
        await respond(message, output)
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
            "**`Available Commands:`**\n"
            "`.s [season]      → Show average stats (default: current season)`\n"
            "`.p [id]          → List PLTE players or show details by ID`\n"
            "`.P <name>        → Search for player with name expression`\n"
            "`.S               → List last 10 seasons`\n"
            "`.S <num> [div]   → Add/update season`\n"
            "`.a               → List aliases for PLTE team`\n"
            "`.v               → List vehicles`\n"
            "`.t               → List teamevents`\n"
            "`.t <id>          → Show teamevent with vehicles`\n"
            "`.t add ...       → Add teamevent (name year/week vehicles)`\n"
            "`    example:     .t add Best Event 2025/38 hc,ro`\n"
            "`.m               → List matches`\n"
            "`.h               → Show this help`\n"
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

