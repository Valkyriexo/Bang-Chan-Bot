import discord
from discord import app_commands
from discord.ext import commands

import database as db
import cards_data as cd


class GiftConfirmView(discord.ui.View):
    def __init__(self, sender: discord.Member, recipient: discord.Member,
                 card: dict, instance_id: int):
        super().__init__(timeout=60)
        self.sender = sender
        self.recipient = recipient
        self.card = card
        self.instance_id = instance_id
        self.result = None

    @discord.ui.button(label="Accept Gift", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.recipient.id:
            await interaction.response.send_message("This gift isn't for you!", ephemeral=True)
            return

        inst = await db.get_card_instance(self.instance_id)
        if not inst or inst["user_id"] != str(self.sender.id):
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(
                content="❌ Gift failed — the card is no longer available.", view=self
            )
            self.result = "failed"
            self.stop()
            return

        await db.transfer_card(self.instance_id, str(self.recipient.id))
        await db.log_gift(
            str(self.sender.id), self.sender.display_name,
            str(self.recipient.id), self.recipient.display_name,
            self.card["id"], self.card["name"],
        )

        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="🎁 Gift Accepted!",
            description=(
                f"{self.sender.mention} gifted {self.card['emoji']} **{self.card['name']}** "
                f"to {self.recipient.mention}!"
            ),
            color=cd.RARITY_COLORS[self.card["rarity"]],
        )
        embed.add_field(name="Rarity", value=cd.RARITY_STARS[self.card["rarity"]], inline=True)
        if self.card.get("image_url"):
            embed.set_thumbnail(url=self.card["image_url"])
        self.result = "accepted"
        await interaction.response.edit_message(content=None, embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.recipient.id, self.sender.id):
            await interaction.response.send_message("You're not part of this gift!", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True

        self.result = "declined"
        await interaction.response.edit_message(
            content=f"❌ {self.recipient.display_name} declined the gift.",
            embed=None,
            view=self,
        )
        self.stop()

    async def on_timeout(self):
        self.result = "timeout"
        for child in self.children:
            child.disabled = True


class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="shop", description="Browse cards for sale")
    async def shop(self, interaction: discord.Interaction):
        listings = await db.get_listings()
        if not listings:
            await interaction.response.send_message("The shop is empty! Use `/inventory` to sell a card.", ephemeral=True)
            return

        lines = []
        for listing in listings[:20]:
            card = cd.ALL_CARDS.get(listing["card_id"])
            if not card:
                continue
            num = card.get("card_number", "?")
            group = f" · {card['group']}" if card.get("group") else ""
            lines.append(
                f"`#{listing['id']}` {card['emoji']} **{card['name']}**{group} "
                f"· {cd.RARITY_STARS[card['rarity']]} · 🪙 **{listing['price']:,}** · by {listing['seller_name']}"
            )

        embed = discord.Embed(title="🏪 Card Shop", description="\n".join(lines), color=0x5865f2)
        embed.set_footer(text="Use /buy <id> to purchase · Open /inventory to list your own")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Buy a card from the shop")
    @app_commands.describe(listing_id="The listing ID from /shop")
    async def buy(self, interaction: discord.Interaction, listing_id: int):
        await db.ensure_user(str(interaction.user.id), interaction.user.display_name)

        listing = await db.get_listing(listing_id)
        if not listing:
            await interaction.response.send_message(
                f"Listing `#{listing_id}` not found. It may have already been sold.", ephemeral=True
            )
            return

        if listing["seller_id"] == str(interaction.user.id):
            await interaction.response.send_message("You can't buy your own listing!", ephemeral=True)
            return

        card = cd.ALL_CARDS.get(listing["card_id"])
        if not card:
            await interaction.response.send_message("This card no longer exists.", ephemeral=True)
            return

        price = listing["price"]
        success = await db.spend_coins(str(interaction.user.id), price)
        if not success:
            coins = await db.get_coins(str(interaction.user.id))
            await interaction.response.send_message(
                f"Not enough coins! You have **{coins:,}** but need **{price:,}**.", ephemeral=True
            )
            return

        await db.transfer_card(listing["user_card_id"], str(interaction.user.id))
        await db.remove_listing(listing_id)
        await db.add_coins(listing["seller_id"], price)

        embed = discord.Embed(
            title="✅ Purchase Complete!",
            description=f"You bought {card['emoji']} **{card['name']}** for 🪙 **{price:,} coins**!",
            color=cd.RARITY_COLORS[card["rarity"]],
        )
        if card.get("image_url"):
            embed.set_thumbnail(url=card["image_url"])
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="delist", description="Remove your card listing from the shop")
    @app_commands.describe(listing_id="The listing ID to remove")
    async def delist(self, interaction: discord.Interaction, listing_id: int):
        listing = await db.get_listing(listing_id)
        if not listing:
            await interaction.response.send_message(f"Listing `#{listing_id}` not found.", ephemeral=True)
            return
        if listing["seller_id"] != str(interaction.user.id):
            await interaction.response.send_message("You can only remove your own listings!", ephemeral=True)
            return

        await db.remove_listing(listing_id)
        card = cd.ALL_CARDS.get(listing["card_id"])
        name = card["name"] if card else listing["card_id"]
        await interaction.response.send_message(
            f"✅ Removed **{name}** (listing `#{listing_id}`) from the shop.", ephemeral=True
        )

    @app_commands.command(name="gift", description="Gift a card to another player")
    @app_commands.describe(
        user="The player to receive the gift",
        card_name="The card to give (name or #number)",
    )
    async def gift(self, interaction: discord.Interaction, user: discord.Member, card_name: str):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't gift a card to yourself!", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("You can't gift cards to bots!", ephemeral=True)
            return

        card = cd.find_card(card_name)
        if not card:
            await interaction.response.send_message(f"Card **{card_name}** not found.", ephemeral=True)
            return

        await db.ensure_user(str(interaction.user.id), interaction.user.display_name)
        await db.ensure_user(str(user.id), user.display_name)

        instance_id = await db.find_user_card_instance(str(interaction.user.id), card["id"])
        if instance_id is None:
            await interaction.response.send_message(
                f"You don't have a free **{card['name']}** to gift.", ephemeral=True
            )
            return

        view = GiftConfirmView(
            sender=interaction.user, recipient=user, card=card, instance_id=instance_id
        )

        embed = discord.Embed(
            title="🎁 Incoming Gift!",
            description=(
                f"{interaction.user.mention} wants to gift you "
                f"{card['emoji']} **{card['name']}**!\n\n"
                f"Do you want to accept?"
            ),
            color=cd.RARITY_COLORS[card["rarity"]],
        )
        embed.add_field(name="Rarity", value=cd.RARITY_STARS[card["rarity"]], inline=True)
        if card.get("group"):
            embed.add_field(name="Group", value=card["group"], inline=True)
        if card.get("image_url"):
            embed.set_image(url=card["image_url"])
        embed.set_footer(text=f"Gift offer expires in 60 seconds · {user.display_name} must respond")
        await interaction.response.send_message(embed=embed, view=view)

        await view.wait()
        if view.result == "timeout":
            for child in view.children:
                child.disabled = True
            try:
                await interaction.edit_original_response(
                    content=f"⏰ Gift offer expired — {user.display_name} didn't respond.",
                    embed=None,
                    view=view,
                )
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ShopCog(bot))
