import discord
from discord.ext import commands
import os
import asyncio

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

COGS = ["cogs.dev", "cogs.moderation", "cogs.logging", "cogs.automod"]

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

async def main():
    async with bot:
        for cog in COGS:
            await bot.load_extension(cog)
        await bot.start(os.environ["DISCORD_TOKEN"])

asyncio.run(main())
