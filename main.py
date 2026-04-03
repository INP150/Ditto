import os
import discord
import subprocess
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv 

from const import EMOJI_MAP
from message_helpers import gather_message_parts

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready() -> None:
    """Booting the bot"""
    await bot.tree.sync()
    print(f"{bot.user} is online!")


@bot.event
async def on_message(msg) -> None:
    """Checks all messages from users and add reactions if the text inlcudes defined words"""
    if msg.author.bot: # ignore messages from bots (including self) 
        return

    parts = gather_message_parts(msg)

    combined = " ".join([p for p in parts if p])

    triggers = EMOJI_MAP

    # collect reactions to add (avoid duplicates)
    pending_reactions = []
    for key, emoji in triggers.items():
        if key in combined and emoji not in pending_reactions:
            pending_reactions.append(emoji)

    if pending_reactions:
        print("Reaction trigger(s) detected in message/embed:", combined)
        add_reactions_to_message(msg, pending_reactions)
    await bot.process_commands(msg)


@bot.tree.command(name="ping", description="Check the bot's latency")
async def ping(interaction: discord.Interaction) -> None:
    """Command to check the ping of the bot"""
    latency = bot.latency * 1000  # Convert to milliseconds
    await interaction.response.send_message(f"Pong! Latency: {latency:.2f} ms")


@bot.tree.command(name="greet", description="Greet the user")
async def greet(interaction: discord.Interaction) -> None:
    """Simple command to greet the user"""
    await interaction.response.send_message(f"Hello, {interaction.user.mention}!")


@bot.tree.command(name="version", description="Get the bot's version")
async def version(interaction: discord.Interaction) -> None:
    """Command that shows on which commit the bot runs right now"""
    version = get_latest_commit_hash()
    await interaction.response.send_message(f"{version}")


def get_latest_commit_hash() -> str:
    """Returns the short version of the latest git commit hash"""
    return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()


def add_reactions_to_message(msg, emojis) -> None:
    """Add a list of emojis as reactions to a message."""
    for emoji in emojis:
        try:
            msg.add_reaction(emoji)
        except discord.Forbidden:
            print("Cannot add reactions: missing Add Reactions permission.")
        except discord.HTTPException as e:
            print("Failed to add reaction:", e)
        except Exception as e:
            print("Unexpected error while adding reactions:", e)


if __name__ == "__main__":
    bot.run(TOKEN)
