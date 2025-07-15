import discord
from discord import app_commands
from secrets import TOKEN
import sqlite3
import traceback
from collections import defaultdict

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

        self.tree.clear_commands(guild=guild)
        self.tree.add_command(show_players, guild=guild)
        self.tree.add_command(show_help, guild=guild)
        self.tree.add_command(show_matchscores, guild=guild)
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

def get_matchscores_grouped():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                ms.id,
                m.id AS match_id,
                m.start,
                m.opponent,
                s.name AS season_name,
                s.division,
                p.name AS player_name,
                ms.score
            FROM matchscore ms
            JOIN players p ON ms.player_id = p.id
            JOIN match m ON ms.match_id = m.id
            JOIN season s ON m.season_number = s.number
            ORDER BY m.start DESC, ms.score DESC
            LIMIT 30
        """)
        rows = cur.fetchall()

    grouped = defaultdict(list)
    for sid, mid, date, opponent, season, division, player, score in rows:
        key = (mid, date, opponent, season, division)
        grouped[key].append((sid, player, score))
    return grouped

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

@app_commands.command(name="ms", description="Zeigt die letzten Matchscores gruppiert")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def show_matchscores(interaction: discord.Interaction):
    print("⚙️ /ms wurde getriggert")
    if interaction.channel.id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("⛔ Nicht erlaubt in diesem Kanal.", ephemeral=True)
        return

    try:
        grouped_scores = get_matchscores_grouped()
        if not grouped_scores:
            await interaction.response.send_message("Keine Matchscores gefunden.")
            return

        reply = ""
        for (mid, date, opponent, season, division), entries in grouped_scores.items():
            reply += f"Match: {mid} | Gegner: {opponent} | Datum: {date} | Season: {season} | Division: {division}\n"
            reply += f"{'ID':<3} {'Spieler':<20} {'Score':>5}\n"
            reply += "-" * 40 + "\n"
            for sid, player, score in entries:
                reply += f"{sid:<3} {player:<20} {score:>5}\n"
            reply += "\n"

        await interaction.response.send_message(f"```\n{reply}```")
    except Exception as e:
        print("❌ Fehler bei /ms:")
        traceback.print_exc()
        await interaction.response.send_message("Fehler beim Anzeigen der Matchscores.", ephemeral=True)

@app_commands.command(name="help", description="Zeigt eine Übersicht aller verfügbaren Befehle")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def show_help(interaction: discord.Interaction):
    print("⚙️ /help wurde getriggert")
    try:
        help_text = (
            "**Verfügbare Befehle:**\n"
            "`/pl` – Zeigt alle aktiven Spieler\n"
            "`/ms` – Zeigt die letzten Matchscores gruppiert\n"
            "`/help` – Zeigt diese Hilfeübersicht\n"
        )
        await interaction.response.send_message(help_text, ephemeral=True)
    except Exception as e:
        print("❌ Fehler bei /help:")
        traceback.print_exc()
        await interaction.response.send_message("Fehler bei /help", ephemeral=True)

client.run(TOKEN)

