import discord
from discord import app_commands
from secrets import TOKEN
import sqlite3

DB_PATH = "db/hcr2.db"
ALLOWED_CHANNEL_ID = 1394750333129068564

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("✅ Slash-Commands synchronisiert")

client = MyClient()

def get_active_players():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT name, alias, garage_power FROM players
            WHERE active = 1
            ORDER BY garage_power DESC
        """)
        return cur.fetchall()

# Slash-Command-Gruppe: /player
player_group = app_commands.Group(name="player", description="Spielerbezogene Befehle")

@player_group.command(name="list", description="Zeigt alle aktiven Spieler")
async def player_list(interaction: discord.Interaction):
    if interaction.channel.id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("⛔ Nicht erlaubt in diesem Kanal.", ephemeral=True)
        return

    players = get_active_players()
    if not players:
        await interaction.response.send_message("Keine aktiven Spieler gefunden.")
        return

    reply = f"{'Name':<20} {'Alias':<15} {'GP':>6}\n"
    reply += "-" * 45 + "\n"
    for name, alias, gp in players:
        reply += f"{name:<20} {alias or '':<15} {gp:>6}\n"

    await interaction.response.send_message(f"```\n{reply}```")

# Gruppe registrieren
client.tree.add_command(player_group)

client.run(TOKEN)

