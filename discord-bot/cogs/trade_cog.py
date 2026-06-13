import discord
from discord import app_commands
from discord.ext import commands

import database as db
import cards_data as cd


class TradeView(discord.ui.View):
    def __init__(self, initiator: discord.Member, target: discord.Member,
                 offered_instance_id: int, offered_card: dict,
                 wanted_instance_id: int, wanted_card: dict):
        super().__init__(timeout=120)
        self.initiator = initiator
        self.target = target
        self.offered_instance_id = offered_instance_id
        self.offered_card = offered_card
        self.wanted_instance_id = wanted_instance_id
        self.wanted_card = wanted_card
        self.result = None

    @discord.ui.button(label="Accept Trade", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Only the trade target can accept this!", ephemeral=True)
            return

        inst1 = await db.get_card_instance(self.offered_instance_id)
        inst2 = await db.get_card_instance(self.wanted_instance_id)

        if not inst1 or inst1["user_id"] != str(self.initiator.id):
            await interaction.response.send_message(
                "Trade failed — the offered card is no longer available.", ephemeral=False
            )
            self.result = "failed"
            self.stop()
            return

        if not inst2 or inst2["user_id"] != str(self.target.id):
            await interaction.response.send_message(
                "Trade failed — your card is no longer available.", ephemeral=False
            )
            self.result = "failed"
            self.stop()
            return

        await db.transfer_card(self.offered_instance_id, str(self.target.id))
        await db.transfer_card(self.wanted_instance_id, str(self.initiator.id))

        self.result = "accepted"
        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="🤝 Trade Complete!",
            description=(
                f"{self.initiator.mention} gave **{self.offered_card['emoji']} {self.offered_card['name']}**\n"
                f"{self.target.mention} gave **{self.wanted_card['emoji']} {self.wanted_card['name']}**"
            ),
            color=0x4caf50,
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Decline Trade", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.target.id, self.initiator.id):
            await interaction.response.send_message("You're not part of this trade!", ephemeral=True)
            return

        self.result = "declined"
        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="❌ Trade Declined",
            description=f"The trade between {self.initiator.mention} and {self.target.mention} was declined.",
            color=0xf44336,
        )
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        self.result = "timeout"
        for child in self.children:
            child.disabled = True


class TradeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="trade", description="Propose a card trade with another player")
    @app_commands.describe(
        user="The player you want to trade with",
        your_card="The card you are offering",
        their_card="The card you want from them",
    )
    async def trade(self, interaction: discord.Interaction, user: discord.Member, your_card: str, their_card: str):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't trade with yourself!", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("You can't trade with a bot!", ephemeral=True)
            return

        offered_card = cd.find_card(your_card)
        if not offered_card:
            await interaction.response.send_message(f"Card **{your_card}** not found.", ephemeral=True)
            return

        wanted_card = cd.find_card(their_card)
        if not wanted_card:
            await interaction.response.send_message(f"Card **{their_card}** not found.", ephemeral=True)
            return

        await db.ensure_user(str(interaction.user.id), interaction.user.display_name)
        await db.ensure_user(str(user.id), user.display_name)

        offered_instance_id = await db.find_user_card_instance(str(interaction.user.id), offered_card["id"])
        if offered_instance_id is None:
            await interaction.response.send_message(
                f"You don't have a free **{offered_card['name']}** to trade (it may be listed in the shop).",
                ephemeral=True,
            )
            return

        wanted_instance_id = await db.find_user_card_instance(str(user.id), wanted_card["id"])
        if wanted_instance_id is None:
            await interaction.response.send_message(
                f"{user.display_name} doesn't have a free **{wanted_card['name']}** to trade.",
                ephemeral=True,
            )
            return

        view = TradeView(
            initiator=interaction.user,
            target=user,
            offered_instance_id=offered_instance_id,
            offered_card=offered_card,
            wanted_instance_id=wanted_instance_id,
            wanted_card=wanted_card,
        )

        embed = discord.Embed(
            title="🤝 Trade Proposal",
            description=f"{user.mention}, you have a trade offer from {interaction.user.mention}!",
            color=0xff9800,
        )
        embed.add_field(
            name=f"{interaction.user.display_name} offers",
            value=f"{offered_card['emoji']} **{offered_card['name']}**\n{cd.RARITY_STARS[offered_card['rarity']]}",
            inline=True,
        )
        embed.add_field(name="⇄", value="\u200b", inline=True)
        embed.add_field(
            name=f"{user.display_name} gives",
            value=f"{wanted_card['emoji']} **{wanted_card['name']}**\n{cd.RARITY_STARS[wanted_card['rarity']]}",
            inline=True,
        )
        embed.set_footer(text="Trade expires in 2 minutes")
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(TradeCog(bot))
