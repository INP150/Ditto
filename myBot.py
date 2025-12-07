import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import asyncio
from collections import deque

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} is online!")

@bot.event
async def on_message(msg):
    # ignore messages from bots (including self)
    if msg.author.bot:
        return

    # Gather message text + embed text (title, description, fields, footer, author)
    parts = [msg.content or ""]
    for embed in msg.embeds:
        if getattr(embed, "title", None):
            parts.append(embed.title)
        if getattr(embed, "description", None):
            parts.append(embed.description)
        footer = getattr(embed, "footer", None)
        if footer and getattr(footer, "text", None):
            parts.append(footer.text)
        author = getattr(embed, "author", None)
        if author and getattr(author, "name", None):
            parts.append(author.name)
        for f in getattr(embed, "fields", []) or []:
            if getattr(f, "name", None):
                parts.append(f.name)
            if getattr(f, "value", None):
                parts.append(f.value)

    combined = " ".join([p for p in parts if p])

    # map shortcodes and unicode variants to the emoji to react with
    triggers = {
        ":+1:": "👍", ":thumbsup:": "👍", "👍": "👍",
        ":-1:": "👎", ":thumbsdown:": "👎", "👎": "👎",
    }

    # collect reactions to add (avoid duplicates)
    to_add = []
    for key, emoji in triggers.items():
        if key in combined and emoji not in to_add:
            to_add.append(emoji)

    if to_add:
        print("Reaction trigger(s) detected in message/embed:", combined)
        for emoji in to_add:
            try:
                await msg.add_reaction(emoji)
            except discord.Forbidden:
                print("Cannot add reactions: missing Add Reactions permission.")
            except discord.HTTPException as e:
                print("Failed to add reaction:", e)
            except Exception as e:
                print("Unexpected error while adding reactions:", e)

    await bot.process_commands(msg)

@bot.tree.command(name="ping", description="Check the bot's latency")
async def ping(interaction: discord.Interaction):
    latency = bot.latency * 1000  # Convert to milliseconds
    await interaction.response.send_message(f"Pong! Latency: {latency:.2f} ms")

@bot.tree.command(name="greet", description="Greet the user")
async def greet(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hello, {interaction.user.mention}!")

bot.run(TOKEN)
