import discord
from discord import app_commands
from discord.ext import commands
import time

import database as db
import cards_data as cd

DROP_COOLDOWNS: dict[int, float] = {}
DROP_COOLDOWN_SECONDS = 30
CARDS_PER_PAGE = 12

# Bang Chan Bot brand colour (gold)
BRAND_COLOR = 0xffd700

# Shared URL on drop embeds so Discord renders them as a side-by-side gallery
_GALLERY_URL = "https://bangchanbot.app"


def build_card_embed(card: dict, title: str = None, footer: str = None) -> discord.Embed:
    rarity = card["rarity"]
    embed = discord.Embed(
        title=title or f"{card['emoji']} {card['name']}",
        description=card["description"],
        color=cd.RARITY_COLORS[rarity],
    )
    embed.add_field(name="Rarity", value=cd.RARITY_STARS[rarity], inline=True)
    if card.get("idol"):
        embed.add_field(name="Idol", value=card["idol"], inline=True)
    if card.get("group"):
        embed.add_field(name="Group", value=card["group"], inline=True)
    num = card.get("card_number")
    if num:
        embed.add_field(name="Card #", value=f"#{num}", inline=True)
    if card.get("image_url"):
        embed.set_image(url=card["image_url"])
    if footer:
        embed.set_footer(text=footer)
    return embed


def build_drop_embed(card: dict, option_num: int) -> discord.Embed:
    """Minimal drop embed — image only when available, shared URL triggers Discord gallery layout."""
    rarity = card["rarity"]
    idol_line = f" · {card['idol']}" if card.get("idol") else ""
    if card.get("image_url"):
        embed = discord.Embed(url=_GALLERY_URL, color=cd.RARITY_COLORS[rarity])
        embed.set_image(url=card["image_url"])
        embed.set_footer(text=f"Card {option_num}  ·  {card['name']}{idol_line}  ·  {cd.RARITY_STARS[rarity]}")
    else:
        embed = discord.Embed(
            title=f"{card['emoji']}  {card['name']}",
            description=f"{cd.RARITY_STARS[rarity]}{idol_line}",
            color=cd.RARITY_COLORS[rarity],
            url=_GALLERY_URL,
        )
        embed.set_footer(text=f"Card {option_num}")
    return embed


class PickButton(discord.ui.Button):
    def __init__(self, card: dict, index: int):
        super().__init__(
            label=str(index + 1),
            style=discord.ButtonStyle.secondary,
            custom_id=f"pick_{index}",
            row=0,
        )
        self.card = card
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: DropView = self.view
        if view.claimed:
            await interaction.response.send_message(
                "Someone already snagged a card from this drop!", ephemeral=True
            )
            return

        view.claimed = True
        view.claimed_by = interaction.user
        view.chosen_card = self.card

        await db.ensure_user(str(interaction.user.id), interaction.user.display_name)
        await db.add_card_to_user(str(interaction.user.id), self.card["id"])

        for child in view.children:
            child.disabled = True

        embed = build_card_embed(
            self.card,
            title=f"{self.card['emoji']} {self.card['name']} — Claimed!",
            footer=f"🎉 Added to {interaction.user.display_name}'s binder!",
        )
        await interaction.response.edit_message(
            content=f"📸 **{interaction.user.display_name}** snagged a photocard!",
            embeds=[embed],
            view=view,
        )
        view.stop()


class DropView(discord.ui.View):
    def __init__(self, cards: list[dict]):
        super().__init__(timeout=60)
        self.cards = cards
        self.claimed = False
        self.claimed_by = None
        self.chosen_card = None
        for i, card in enumerate(cards):
            self.add_item(PickButton(card, i))

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
            child.style = discord.ButtonStyle.secondary


def _stars_display(rarity: str) -> str:
    n = int(rarity[0]) if rarity and rarity[0].isdigit() else 1
    return "⭐" * n + "☆" * (5 - n)


def _group_code(group: str | None) -> str:
    codes = {"Stray Kids": "SKZ"}
    if not group:
        return "UNK"
    return codes.get(group, group[:3].upper())


def _sort_unique(unique: list, sort_by: str) -> list:
    if sort_by == "idol":
        return sorted(unique, key=lambda x: (x[0].get("idol") or "ZZZ", x[0]["name"]))
    if sort_by == "name":
        return sorted(unique, key=lambda x: x[0]["name"])
    if sort_by == "number":
        return sorted(unique, key=lambda x: x[0].get("card_number", 999))
    return sorted(unique, key=lambda x: (cd.RARITY_ORDER.index(x[0]["rarity"]), x[0]["name"]))


class SellModal(discord.ui.Modal, title="List Card for Sale"):
    price_input = discord.ui.TextInput(
        label="Price (coins)",
        placeholder="e.g. 500",
        min_length=1,
        max_length=6,
    )

    def __init__(self, card: dict, user_id: str, username: str):
        super().__init__()
        self.card = card
        self.user_id = user_id
        self.username = username

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.price_input.value.strip().replace(",", ""))
        except ValueError:
            await interaction.response.send_message("Enter a valid number.", ephemeral=True)
            return
        if price < 1 or price > 100_000:
            await interaction.response.send_message("Price must be 1 – 100,000 coins.", ephemeral=True)
            return

        instance_id = await db.find_user_card_instance(self.user_id, self.card["id"])
        if instance_id is None:
            await interaction.response.send_message(
                "You don't have a free copy of this card to sell.", ephemeral=True
            )
            return

        listing_id = await db.create_listing(
            self.user_id, self.username, instance_id, self.card["id"], price,
        )
        embed = discord.Embed(
            title="🏪 Card Listed!",
            description=(
                f"{self.card['emoji']} **{self.card['name']}** listed for **{price:,} coins**.\n"
                f"Listing ID: `#{listing_id}`"
            ),
            color=cd.RARITY_COLORS[self.card["rarity"]],
        )
        if self.card.get("image_url"):
            embed.set_thumbnail(url=self.card["image_url"])
        embed.set_footer(text="Use /delist to remove your listing")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class SortSelect(discord.ui.Select):
    def __init__(self, current: str):
        options = [
            discord.SelectOption(label="Sort by: Rarity", value="rarity", default=(current == "rarity")),
            discord.SelectOption(label="Sort by: Idol",   value="idol",   default=(current == "idol")),
            discord.SelectOption(label="Sort by: Name",   value="name",   default=(current == "name")),
            discord.SelectOption(label="Sort by: Card #", value="number", default=(current == "number")),
        ]
        super().__init__(placeholder="Sort by: Rarity", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view: InventoryView = self.view
        view.sort_by = self.values[0]
        view.unique_cards = _sort_unique(view.all_unique, view.sort_by)
        view.page = 0
        view._rebuild_components()
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class InventoryView(discord.ui.View):
    def __init__(self, all_instances: list[dict], target: discord.Member,
                 viewer: discord.Member, coins: int,
                 filter_desc: str = "", sort_by: str = "rarity"):
        super().__init__(timeout=180)

        counts: dict[str, int] = {}
        for inst in all_instances:
            counts[inst["card_id"]] = counts.get(inst["card_id"], 0) + 1

        self.all_unique: list = []
        for card_id, count in counts.items():
            card = cd.ALL_CARDS.get(card_id)
            if card:
                self.all_unique.append((card, count))

        self.sort_by = sort_by
        self.unique_cards = _sort_unique(self.all_unique, sort_by)
        self.target = target
        self.viewer = viewer
        self.coins = coins
        self.filter_desc = filter_desc
        self.page = 0
        self.is_own = (target.id == viewer.id)
        self._rebuild_components()

    def _rebuild_components(self):
        self.clear_items()
        self.add_item(SortSelect(self.sort_by))
        total = len(self.unique_cards)

        first_btn = discord.ui.Button(label="◀◀", style=discord.ButtonStyle.secondary,
                                      disabled=(self.page == 0), row=1)
        first_btn.callback = self._first
        self.add_item(first_btn)

        prev_btn = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary,
                                     disabled=(self.page == 0), row=1)
        prev_btn.callback = self._prev
        self.add_item(prev_btn)

        page_label = discord.ui.Button(
            label=f"Page {self.page + 1}/{max(1, total)}",
            style=discord.ButtonStyle.secondary, disabled=True, row=1,
        )
        self.add_item(page_label)

        next_btn = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary,
                                     disabled=(self.page >= total - 1), row=1)
        next_btn.callback = self._next
        self.add_item(next_btn)

        last_btn = discord.ui.Button(label="▶▶", style=discord.ButtonStyle.secondary,
                                     disabled=(self.page >= total - 1), row=1)
        last_btn.callback = self._last
        self.add_item(last_btn)

        if self.is_own and self.unique_cards:
            card, _ = self.unique_cards[self.page]
            if card["rarity"] != "5star":
                sell_btn = discord.ui.Button(label="Sell", style=discord.ButtonStyle.danger, row=2)
                sell_btn.callback = self._sell
                self.add_item(sell_btn)

    async def _first(self, interaction: discord.Interaction):
        self.page = 0
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _next(self, interaction: discord.Interaction):
        self.page = min(len(self.unique_cards) - 1, self.page + 1)
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _last(self, interaction: discord.Interaction):
        self.page = max(0, len(self.unique_cards) - 1)
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _sell(self, interaction: discord.Interaction):
        if interaction.user.id != self.viewer.id:
            await interaction.response.send_message("This isn't your binder!", ephemeral=True)
            return
        if not self.unique_cards:
            return
        card, _ = self.unique_cards[self.page]
        modal = SellModal(card, str(interaction.user.id), interaction.user.display_name)
        await interaction.response.send_modal(modal)

    def build_embed(self) -> discord.Embed:
        if not self.unique_cards:
            embed = discord.Embed(
                description="No photocards found. Use `/drop` to get some!",
                color=BRAND_COLOR,
            )
            embed.set_author(
                name=self.target.display_name,
                icon_url=str(self.target.display_avatar.url),
            )
            return embed

        card, count = self.unique_cards[self.page]
        rarity = card["rarity"]
        num = card.get("card_number", "?")
        group = card.get("group") or "—"
        group_code = _group_code(card.get("group"))
        stars = _stars_display(rarity)
        total_unique = len(self.unique_cards)
        total_copies = sum(c for _, c in self.all_unique)

        desc = (
            f"**{card['name']}**\n\n"
            f"{num}. {card['name']}\n\n"
            f"🌸 **Group:** {group}\n"
            f"🌿 **Copies:** {count}\n"
            f"🌱 **Card ID:** {group_code}#{num}\n"
            f"({stars})"
        )

        embed = discord.Embed(description=desc, color=cd.RARITY_COLORS[rarity])
        embed.set_author(
            name=self.target.display_name,
            icon_url=str(self.target.display_avatar.url),
        )
        if card.get("image_url"):
            embed.set_image(url=card["image_url"])

        filter_note = f" · {self.filter_desc}" if self.filter_desc else ""
        embed.set_footer(
            text=f"{total_unique} unique · {total_copies} total · 🪙 {self.coins:,} coins{filter_note}"
        )
        return embed


class CardsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="drop", description="Drop 3 photocards — be first to grab one!")
    async def drop(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        now = time.time()
        remaining = DROP_COOLDOWN_SECONDS - (now - DROP_COOLDOWNS.get(channel_id, 0))
        if remaining > 0:
            await interaction.response.send_message(
                f"⏳ Photocards are resting! Try again in **{int(remaining)}s**.", ephemeral=True
            )
            return

        if not cd.ALL_CARDS or not any(not cd.is_expired(c) for c in cd.ALL_CARDS.values()):
            await interaction.response.send_message(
                "🃏 The drop pool is empty! Ask a staff member to add some photocards first.",
                ephemeral=True,
            )
            return

        DROP_COOLDOWNS[channel_id] = now
        cards = [cd.get_random_card() for _ in range(3)]
        view = DropView(cards)
        embeds = [build_drop_embed(card, i + 1) for i, card in enumerate(cards)]

        await interaction.response.send_message(
            content=f"{interaction.user.mention} is dropping a set of 3 cards!",
            embeds=embeds,
            view=view,
        )

        await view.wait()
        if not view.claimed:
            for child in view.children:
                child.disabled = True
            try:
                await interaction.edit_original_response(
                    content="📭 **The photocards expired — nobody claimed them.**",
                    embeds=embeds,
                    view=view,
                )
            except Exception:
                pass

    @app_commands.command(name="inventory", description="View your photocard binder")
    @app_commands.describe(
        user="Whose binder to view (default: yourself)",
        rarity="Filter by rarity",
        group="Filter by group name",
        idol="Filter by idol name",
        search="Search cards by name",
    )
    @app_commands.choices(rarity=[
        app_commands.Choice(name="⭐ 1-Star", value="1star"),
        app_commands.Choice(name="⭐⭐ 2-Star", value="2star"),
        app_commands.Choice(name="⭐⭐⭐ 3-Star", value="3star"),
        app_commands.Choice(name="⭐⭐⭐⭐ 4-Star", value="4star"),
        app_commands.Choice(name="⭐⭐⭐⭐⭐ 5-Star", value="5star"),
    ])
    async def inventory(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        rarity: str = None,
        group: str = None,
        idol: str = None,
        search: str = None,
    ):
        target = user or interaction.user
        await db.ensure_user(str(target.id), target.display_name)
        all_instances = await db.get_user_cards(str(target.id))

        filtered = []
        for inst in all_instances:
            card = cd.ALL_CARDS.get(inst["card_id"])
            if not card:
                continue
            if rarity and card["rarity"] != rarity:
                continue
            if group and group.lower() not in (card.get("group") or "").lower():
                continue
            if idol and idol.lower() not in (card.get("idol") or "").lower():
                continue
            if search and search.lower() not in card["name"].lower():
                continue
            filtered.append(inst)

        filtered.sort(key=lambda inst: (
            cd.RARITY_ORDER.index(cd.ALL_CARDS.get(inst["card_id"], {}).get("rarity", "common")),
            cd.ALL_CARDS.get(inst["card_id"], {}).get("name", ""),
        ))

        if not filtered:
            msg = "No photocards found" + (" matching those filters." if any([rarity, group, idol, search]) else ". Use `/drop` to get some!")
            await interaction.response.send_message(msg, ephemeral=True)
            return

        filter_parts = []
        if rarity:
            filter_parts.append(cd.RARITY_STARS[rarity])
        if group:
            filter_parts.append(f"Group: {group}")
        if idol:
            filter_parts.append(f"Idol: {idol}")
        if search:
            filter_parts.append(f'"{search}"')

        coins = await db.get_coins(str(target.id))
        view = InventoryView(
            filtered, target, interaction.user, coins,
            filter_desc=" · ".join(filter_parts),
        )
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="search", description="Search photocards by name, idol, or group")
    @app_commands.describe(query="Search term (name, idol, or group)")
    async def search(self, interaction: discord.Interaction, query: str):
        q = query.lower()
        results = [
            c for c in cd.ALL_CARDS.values()
            if q in c["name"].lower()
            or q in (c.get("group") or "").lower()
            or q in (c.get("idol") or "").lower()
        ]

        if not results:
            await interaction.response.send_message(f"No photocards found matching **{query}**.", ephemeral=True)
            return

        results.sort(key=lambda c: (cd.RARITY_ORDER.index(c["rarity"]), c["name"]))
        lines = []
        for c in results[:20]:
            num = c.get("card_number", "?")
            idol = f" · {c['idol']}" if c.get("idol") else ""
            group = f" · {c['group']}" if c.get("group") else ""
            lines.append(f"`#{num}` {c['emoji']} **{c['name']}**{idol}{group} · {cd.RARITY_STARS[c['rarity']]}")

        embed = discord.Embed(
            title=f"🔍 Results for \"{query}\"",
            description="\n".join(lines),
            color=BRAND_COLOR,
        )
        if len(results) > 20:
            embed.set_footer(text=f"Showing 20 of {len(results)} — narrow your search for more specific results")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="cards", description="Browse all photocards in the collection")
    @app_commands.describe(rarity="Filter by rarity")
    @app_commands.choices(rarity=[
        app_commands.Choice(name="⭐ 1-Star", value="1star"),
        app_commands.Choice(name="⭐⭐ 2-Star", value="2star"),
        app_commands.Choice(name="⭐⭐⭐ 3-Star", value="3star"),
        app_commands.Choice(name="⭐⭐⭐⭐ 4-Star", value="4star"),
        app_commands.Choice(name="⭐⭐⭐⭐⭐ 5-Star", value="5star"),
    ])
    async def cards_list(self, interaction: discord.Interaction, rarity: str = None):
        pool = [c for c in cd.ALL_CARDS.values() if not rarity or c["rarity"] == rarity]
        pool.sort(key=lambda c: (cd.RARITY_ORDER.index(c["rarity"]), c.get("card_number", 999)))

        lines_by_rarity: dict[str, list[str]] = {r: [] for r in cd.RARITY_ORDER}
        for c in pool:
            num = c.get("card_number", "?")
            idol = f" · {c['idol']}" if c.get("idol") else ""
            img = " 🖼️" if c.get("image_url") else ""
            lines_by_rarity[c["rarity"]].append(f"`#{num}` {c['emoji']} {c['name']}{idol}{img}")

        rarity_headers = {
            "5star": "⭐⭐⭐⭐⭐ 5-Star (2%)",
            "4star": "⭐⭐⭐⭐ 4-Star (6%)",
            "3star": "⭐⭐⭐ 3-Star (12%)",
            "2star": "⭐⭐ 2-Star (25%)",
            "1star": "⭐ 1-Star (55%)",
        }
        embed = discord.Embed(
            title="📖 Bang Chan Bot — Photocard Index",
            description="All available photocards · 🖼️ = has image · Use `/card #N` to view",
            color=BRAND_COLOR,
        )
        for r in cd.RARITY_ORDER:
            if lines_by_rarity[r]:
                embed.add_field(
                    name=rarity_headers[r],
                    value="\n".join(lines_by_rarity[r]),
                    inline=False,
                )
        embed.set_footer(text=f"{len(pool)} photocards total · STAYs collect them all!")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="profile", description="View a STAY's collection profile")
    @app_commands.describe(user="The STAY to view (default: yourself)")
    async def profile(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        await db.ensure_user(str(target.id), target.display_name)
        stats = await db.get_collection_stats(str(target.id))

        rarity_counts: dict[str, int] = {r: 0 for r in cd.RARITY_ORDER}
        idol_counts: dict[str, int] = {}
        group_counts: dict[str, int] = {}
        rarest_card = None

        for card_id, count in stats["card_counts"].items():
            card = cd.ALL_CARDS.get(card_id)
            if not card:
                continue
            rarity_counts[card["rarity"]] += count
            if card.get("idol"):
                idol_counts[card["idol"]] = idol_counts.get(card["idol"], 0) + count
            if card.get("group"):
                group_counts[card["group"]] = group_counts.get(card["group"], 0) + count
            if rarest_card is None or cd.RARITY_ORDER.index(card["rarity"]) < cd.RARITY_ORDER.index(rarest_card["rarity"]):
                rarest_card = card

        is_self = target == interaction.user
        title = "Your STAY Profile ⭐" if is_self else f"{target.display_name}'s STAY Profile ⭐"

        embed = discord.Embed(title=title, color=BRAND_COLOR)
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(name="📂 Photocards", value=str(stats["total"]), inline=True)
        embed.add_field(name="✨ Unique", value=str(stats["unique"]), inline=True)
        embed.add_field(name="🪙 Coins", value=f"{stats['coins']:,}", inline=True)

        rarity_lines = []
        for r in cd.RARITY_ORDER:
            if rarity_counts[r]:
                rarity_lines.append(f"{cd.RARITY_STARS[r]}: **{rarity_counts[r]}**")
        if rarity_lines:
            embed.add_field(name="📊 By Rarity", value="\n".join(rarity_lines), inline=True)

        if idol_counts:
            top_idols = sorted(idol_counts.items(), key=lambda x: -x[1])[:5]
            embed.add_field(
                name="💜 Bias Cards",
                value="\n".join(f"**{i}**: {n}" for i, n in top_idols),
                inline=True,
            )

        if rarest_card:
            embed.add_field(
                name="👑 Rarest Pull",
                value=f"{rarest_card['emoji']} {rarest_card['name']}\n{cd.RARITY_STARS[rarest_card['rarity']]}",
                inline=True,
            )

        embed.add_field(name="🎁 Gifts Sent", value=str(stats["gifts_sent"]), inline=True)
        embed.add_field(name="🎁 Gifts Received", value=str(stats["gifts_received"]), inline=True)

        recent_gifts = await db.get_gift_history(str(target.id), limit=5)
        if recent_gifts:
            gift_lines = []
            for g in recent_gifts:
                if g["sender_id"] == str(target.id):
                    gift_lines.append(f"➡️ gave **{g['card_name']}** to {g['recipient_name']}")
                else:
                    gift_lines.append(f"⬅️ got **{g['card_name']}** from {g['sender_name']}")
            embed.add_field(name="🕓 Recent Gifts", value="\n".join(gift_lines), inline=False)

        embed.set_footer(text="Stay With Me 🐺 — Stray Kids")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(CardsCog(bot))
