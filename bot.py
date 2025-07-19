import discord
from secrets_config import TOKEN
import subprocess
import traceback

ALLOWED_CHANNEL_ID = [1394750333129068564, 1394909975238934659]
MAX_DISCORD_MSG_LEN = 1990

COMMANDS = {
    ".s": ["stats", "avg"],
    ".S": ["season", "list"],
    ".a": ["stats", "alias"],
    ".v": ["vehicle", "list"],
    ".p": ["player", "list"],  # wird bei .p <id> dynamisch ersetzt
    ".t": ["teamevent", "list"],
    ".m": ["match", "list"],
    ".h": None,  # help
}


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


@client.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.id not in ALLOWED_CHANNEL_ID:
        return

    content = message.content.strip()

    # Prefix commands like ".s", ".p", etc.
    if content.startswith("."):
        parts = content.split()
        cmd = parts[0]
        args = parts[1:] if len(parts) > 0 else []

        # special case: .p <id> → show player details
        if cmd == ".p" and len(args) == 1 and args[0].isdigit():
            output = run_hcr2(["player", "show", args[0]])
            if not output:
                await message.channel.send("⚠️ No data found or error occurred.")
            elif len(output) <= MAX_DISCORD_MSG_LEN:
                await message.channel.send(f"```\n{output}```")
            else:
                await message.channel.send("⚠️ Output too long to display.")
            return

        if cmd == ".h":
            help_text = (
                "**Available Commands:**\n"
                "`.s` → Stats (current season)\n"
                "`.S` → List all seasons\n"
                "`.a` → List aliases for PLTE team\n"
                "`.p` → List all players\n"
                "`.p <id>` → Show player details\n"
                "`.v` → List vehicles\n"
                "`.t` → List teamevents\n"
                "`.m` → List matches\n"
                "`.h` → Show this help\n"
            )
            await message.channel.send(help_text)
            return

        if cmd in COMMANDS:
            base_cmd = COMMANDS[cmd]
            if base_cmd is None:
                return
            full_args = base_cmd + args
            output = run_hcr2(full_args)
            if not output:
                await message.channel.send("⚠️ No data returned or error occurred.")
            elif len(output) <= MAX_DISCORD_MSG_LEN:
                await message.channel.send(f"```\n{output}```")
            else:
                await message.channel.send("⚠️ Output too long to display.")
            return

    # Semicolon-separated score lines
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


client.run(TOKEN)

