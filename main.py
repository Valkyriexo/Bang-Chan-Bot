import discord
from discord.ext import commands
import random
import os

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

cards = [
    "Jaehee #153",
    "Riku #151",
    "Ryo #154",
    "Lisa #127",
    "Jungkook #045"
]

@bot.event
async def on_ready():
    print(f"{bot.user} is online!")

@bot.command()
async def drop(ctx):
    dropped = random.sample(cards, 3)
    msg = "\n".join([f"{i+1}. {card}" for i, card in enumerate(dropped)])
    await ctx.send(f"Cards dropped!\n\n{msg}")

bot.run(os.getenv("TOKEN"))
