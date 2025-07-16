import discord
from discord import app_commands
from secrets import TOKEN
import subprocess
import traceback

ALLOWED_CHANNEL_ID = 1394750333129068564
MAX_DISCORD_MSG_LEN = 1990  

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.add_command(show_stats)
        await self.tree.sync()
        print("✅ /stats-Befehl synchronisiert")


client = MyClient()


def get_stats_output():
    try:
        result = subprocess.run(
            ["python3", "hcr2.py", "stats", "avg"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print("❌ Fehler beim Aufruf von hcr2.py stats avg:")
        print(e)
        return None


@app_commands.command(name="stats", description="Zeigt Rangliste mit Median-Delta der aktuellen Saison")
async def show_stats(interaction: discord.Interaction):
    print("⚙️ /stats wurde getriggert")
    if interaction.channel.id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("⛔ Nicht erlaubt in diesem Kanal.", ephemeral=True)
        return

    try:
        output = get_stats_output()
        if not output:
            await interaction.response.send_message("Fehler beim Abrufen der Statistik.", ephemeral=True)
            return

        if len(output) <= MAX_DISCORD_MSG_LEN:
            await interaction.response.send_message(f"```\n{output}```")
        else:
            await interaction.response.send_message("⚠️ Ausgabe zu lang. Bitte Ausgabe kürzen.", ephemeral=True)

    except Exception as e:
        print("❌ Fehler bei /stats:")
        traceback.print_exc()
        await interaction.response.send_message("Fehler beim Anzeigen der Statistik.", ephemeral=True)


client.run(TOKEN)

