import os
import discord
from discord.ext import commands

import database as db
import cards_data as cd


class CardBot(commands.Bot):
    async def setup_hook(self):
        await db.init_db()

        custom_cards = await db.get_custom_cards()
        for row in custom_cards:
            cd.add_card_to_pool({
                "id": row["card_id"],
                "name": row["name"],
                "emoji": row["emoji"],
                "rarity": row["rarity"],
                "description": row["description"],
                "image_url": row["image_url"],
                "idol": row["idol_name"],
                "group": row["group_name"],
                "added_by": row.get("added_by"),
                "expires_at": row.get("expires_at"),
            }, card_number=row["card_number"])
        print(f"Loaded {len(custom_cards)} custom card(s) from database")

        await self.load_extension("cogs.cards_cog")
        await self.load_extension("cogs.shop_cog")
        await self.load_extension("cogs.trade_cog")
        await self.load_extension("cogs.admin_cog")
        synced = await self.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("Bang Chan Bot is ready! Stay With Me 🐺")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="Stray Kids | /drop for photocards",
            )
        )


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN environment variable is not set.")

    intents = discord.Intents.default()
    intents.message_content = True

    bot = CardBot(command_prefix="!", intents=intents)
    bot.run(token)


if __name__ == "__main__":
    main()
