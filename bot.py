import asyncio
import discord
from discord.ext import commands

from config import DISCORD_TOKEN, require_config
from cogs.ai_chat import AIChatCog


require_config()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="~", intents=intents)


@bot.event
async def on_ready() -> None:
    print("=== BOT START ===")
    print("Discord connected")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


async def main() -> None:
    print("=== COG LOAD ===")
    print("Loading AIChatCog...")
    await bot.add_cog(AIChatCog(bot))
    print("AIChatCog loaded")
    print("Starting bot...")
    await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
