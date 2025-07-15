import discord
from discord import app_commands
from secrets import TOKEN
import sqlite3
import traceback

DB_PATH = "db/hcr2.db"
ALLOWED_CHANNEL_ID = 1394750333129068564
GUILD_ID = 930351245703655454

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)

        # ✅ Neue Commands registrieren
        self.tree.add_command(show_players, guild=guild)
        self.tree.add_command(show_help, guild=guild)
        await self.tree.sync(guild=guild)

        print("✅ Slash-Commands neu synchronisiert")
        print("📋 Registrierte Befehle:")
        for cmd in self.tree.get_commands(guild=guild):
            print(f"  - {cmd.name}")

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

@app_commands.command(name="pl", description="Zeigt alle aktiven Spieler")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def show_players(interaction: discord.Interaction):
    print("⚙️ /pl wurde getriggert")
    if interaction.channel.id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("⛔ Nicht erlaubt in diesem Kanal.", ephemeral=True)
        return

    try:
        players = get_active_players()
        if not players:
            await interaction.response.send_message("Keine aktiven Spieler gefunden.")
            return

        reply = f"{'Name':<20} {'Alias':<15} {'GP':>6}\n"
        reply += "-" * 45 + "\n"
        for name, alias, gp in players:
            reply += f"{name:<20} {alias or '':<15} {gp:>6}\n"

        await interaction.response.send_message(f"```\n{reply}```")
    except Exception as e:
        print("❌ Fehler bei /pl:")
        traceback.print_exc()
        await interaction.response.send_message("Fehler beim Anzeigen der Spieler.", ephemeral=True)

@app_commands.command(name="help", description="Zeigt eine Übersicht aller verfügbaren Befehle")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def show_help(interaction: discord.Interaction):
    print("⚙️ /help wurde getriggert")
    try:
        help_text = (
            "**Verfügbare Befehle:**\n"
            "`/pl` – Zeigt alle aktiven Spieler (sortiert nach Garage Power)\n"
            "`/help` – Zeigt diese Hilfeübersicht\n"
        )
        await interaction.response.send_message(help_text, ephemeral=True)
    except Exception as e:
        print("❌ Fehler bei /help:")
        traceback.print_exc()
        await interaction.response.send_message("Fehler bei /help", ephemeral=True)

client.run(TOKEN)

