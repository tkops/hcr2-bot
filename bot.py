import discord
from discord import app_commands
from secrets import TOKEN
import subprocess
import traceback

ALLOWED_CHANNEL_ID = 1394750333129068564
MAX_DISCORD_MSG_LEN = 1990

ADMINS = set()  # optional für spätere Erweiterung


class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.add_command(show_stats)
        self.tree.add_command(show_vehicles)
        self.tree.add_command(show_players)
        self.tree.add_command(show_teamevents)
        self.tree.add_command(show_seasons)
        self.tree.add_command(show_matches)
        self.tree.add_command(autoadd)
        await self.tree.sync()
        print("✅ Alle Slash-Befehle synchronisiert")


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
        print(f"❌ Fehler bei hcr2.py {' '.join(args)}:")
        print(e)
        return None


async def run_list_command(interaction, get_output_func):
    if interaction.channel.id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("⛔ Nicht erlaubt in diesem Kanal.", ephemeral=True)
        return

    try:
        output = get_output_func()
        if not output:
            await interaction.response.send_message("⚠️ Keine Daten gefunden.", ephemeral=True)
            return

        if len(output) <= MAX_DISCORD_MSG_LEN:
            await interaction.response.send_message(f"```\n{output}```")
        else:
            await interaction.response.send_message("⚠️ Ausgabe zu lang.", ephemeral=True)
    except Exception:
        traceback.print_exc()
        await interaction.response.send_message("❌ Fehler bei der Anzeige.", ephemeral=True)


# ---- Slash-Befehle ----

@app_commands.command(name="stats", description="Zeigt die aktuelle Rangliste")
async def show_stats(interaction: discord.Interaction):
    await run_list_command(interaction, lambda: run_hcr2(["stats", "avg"]))


@app_commands.command(name="vehicles", description="Zeigt alle Fahrzeuge")
async def show_vehicles(interaction: discord.Interaction):
    await run_list_command(interaction, lambda: run_hcr2(["vehicle", "list"]))


@app_commands.command(name="player", description="Zeigt alle Spieler")
async def show_players(interaction: discord.Interaction):
    await run_list_command(interaction, lambda: run_hcr2(["player", "list"]))


@app_commands.command(name="teamevent", description="Zeigt alle Teamevents")
async def show_teamevents(interaction: discord.Interaction):
    await run_list_command(interaction, lambda: run_hcr2(["teamevent", "list"]))


@app_commands.command(name="season", description="Zeigt alle Seasons")
async def show_seasons(interaction: discord.Interaction):
    await run_list_command(interaction, lambda: run_hcr2(["season", "list"]))


@app_commands.command(name="match", description="Zeigt alle Matches")
async def show_matches(interaction: discord.Interaction):
    await run_list_command(interaction, lambda: run_hcr2(["match", "list"]))

@app_commands.command(name="autoadd", description="Berechnet und speichert Punkte automatisch")
async def autoadd(interaction: discord.Interaction):
    await run_list_command(interaction, lambda: run_hcr2(["matchscore", "autoadd"]))



client.run(TOKEN)

