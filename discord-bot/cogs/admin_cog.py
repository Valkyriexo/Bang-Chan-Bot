import math
import re
from datetime import datetime, timedelta, timezone
import discord
from discord import app_commands
from discord.ext import commands

import database as db
import cards_data as cd

DURATION_MAP: dict[str, timedelta | None] = {
    "1h":        timedelta(hours=1),
    "6h":        timedelta(hours=6),
    "12h":       timedelta(hours=12),
    "1d":        timedelta(days=1),
    "3d":        timedelta(days=3),
    "1w":        timedelta(weeks=1),
    "permanent": None,
}

RARITY_EMOJI = {
    "1star": "⭐",
    "2star": "💫",
    "3star": "✨",
    "4star": "🌟",
    "5star": "👑",
}

POOL_PER_PAGE = 6

_RARITY_SORT = {r: i for i, r in enumerate(cd.RARITY_ORDER)}


def slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def era_of(card: dict) -> str:
    name = card["name"]
    if " — " in name:
        return name.split(" — ", 1)[1]
    return name


async def owner_only(interaction: discord.Interaction) -> bool:
    if await interaction.client.is_owner(interaction.user):
        return True
    await interaction.response.send_message(
        "🔒 This command is restricted to the bot owner.", ephemeral=True
    )
    return False


# ── Paginated card pool view ─────────────────────────────────────────────────

class CardPoolView(discord.ui.View):
    _SORT_FN = {
        "num":    lambda c: c.get("card_number", 999),
        "idol":   lambda c: (c.get("idol") or "").lower(),
        "group":  lambda c: (c.get("group") or "").lower(),
        "rarity": lambda c: _RARITY_SORT.get(c["rarity"], 99),
    }
    _SORT_LABELS = {
        "num":    "Card #",
        "idol":   "Idol A–Z",
        "group":  "Group A–Z",
        "rarity": "Rarity",
    }

    def __init__(self, cards: list[dict], filter_label: str):
        super().__init__(timeout=180)
        self._orig = list(cards)
        self.filter_label = filter_label
        self.sort_key = "num"
        self.page = 0
        self._sorted = list(cards)
        self._refresh_buttons()

    # ── helpers ──────────────────────────────────────────────────

    def _apply_sort(self):
        self._sorted = sorted(self._orig, key=self._SORT_FN[self.sort_key])
        self.page = 0

    def _total_pages(self) -> int:
        return max(1, math.ceil(len(self._sorted) / POOL_PER_PAGE))

    def _page_cards(self) -> list[dict]:
        s = self.page * POOL_PER_PAGE
        return self._sorted[s : s + POOL_PER_PAGE]

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self._total_pages() - 1

    # ── embed ─────────────────────────────────────────────────────

    def build_embed(self) -> discord.Embed:
        page_cards   = self._page_cards()
        builtin_total = sum(1 for c in self._sorted if c["id"] in cd.CARDS)
        custom_total  = len(self._sorted) - builtin_total

        lines: list[str] = []
        first_image: str | None = None

        for card in page_cards:
            is_custom = card["id"] not in cd.CARDS
            img_url   = card.get("image_url")
            if img_url and first_image is None:
                first_image = img_url

            img_part   = f" · [🖼️ image]({img_url})" if img_url else ""
            custom_tag = " ✨" if is_custom else ""
            idol_txt   = card.get("idol") or "—"
            group_txt  = card.get("group") or "—"
            era_txt    = era_of(card)
            added_txt  = card.get("added_by")
            num        = card.get("card_number", "?")

            # Expiry label
            expires_at = card.get("expires_at")
            if expires_at:
                try:
                    dt = datetime.fromisoformat(expires_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < datetime.now(timezone.utc):
                        expiry_part = " · ⛔ **expired**"
                    else:
                        ts = int(dt.timestamp())
                        expiry_part = f" · ⏰ <t:{ts}:R>"
                except (ValueError, TypeError):
                    expiry_part = ""
            else:
                expiry_part = " · 🔁 permanent" if is_custom else ""

            sub = f"{idol_txt} · {group_txt} · {era_txt}"
            if is_custom and added_txt:
                sub += f" · by **{added_txt}**"
            sub += expiry_part

            lines.append(
                f"`#{num}` {card['emoji']} **{card['name']}**{custom_tag}{img_part}\n"
                f"-# {sub}"
            )

        embed = discord.Embed(
            title="🃏 Drop Pool",
            description="\n\n".join(lines) or "No cards on this page.",
            color=0x5865F2,
        )
        embed.set_footer(
            text=(
                f"Page {self.page + 1} / {self._total_pages()}  ·  "
                f"{len(self._sorted)} result(s)  ·  "
                f"{builtin_total} built-in  ·  {custom_total} custom ✨  ·  "
                f"Sort: {self._SORT_LABELS[self.sort_key]}\n"
                f"{self.filter_label}"
            )
        )
        if first_image:
            embed.set_image(url=first_image)
        return embed

    # ── buttons ───────────────────────────────────────────────────

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    # ── sort select ───────────────────────────────────────────────

    @discord.ui.select(
        placeholder="Sort by…",
        row=1,
        options=[
            discord.SelectOption(label="Card #",     value="num",    description="Default — sort by card number"),
            discord.SelectOption(label="Idol A–Z",   value="idol",   description="Sort alphabetically by idol name"),
            discord.SelectOption(label="Group A–Z",  value="group",  description="Sort alphabetically by group name"),
            discord.SelectOption(label="Rarity",     value="rarity", description="Sort by rarity tier (low → high)"),
        ],
    )
    async def sort_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.sort_key = select.values[0]
        self._apply_sort()
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


# ── Cog ──────────────────────────────────────────────────────────────────────

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Top-level group ──────────────────────────────────────────
    staff = app_commands.Group(name="staff", description="Staff-only management commands")

    # ── /staff add ───────────────────────────────────────────────
    staff_add = app_commands.Group(name="add", description="Add content", parent=staff)

    @staff_add.command(name="card", description="Add a custom photocard to the drop pool")
    @app_commands.describe(
        idol="Idol name (e.g. Bang Chan)",
        group="Group name (e.g. Stray Kids)",
        era="Era or concept name (e.g. God's Menu) — forms the card title",
        rarity="Drop rate tier",
        duration="How long this card stays in the drop pool (default: Permanent)",
        card_id="Optional: custom card ID (auto-generated if blank)",
        description="Optional flavour text (auto-generated if left blank)",
        image="Attach the photocard image",
        image_url="Or paste a direct image URL",
    )
    @app_commands.choices(
        rarity=[
            app_commands.Choice(name="⭐ 1-Star (55%)",       value="1star"),
            app_commands.Choice(name="⭐⭐ 2-Star (25%)",     value="2star"),
            app_commands.Choice(name="⭐⭐⭐ 3-Star (12%)",   value="3star"),
            app_commands.Choice(name="⭐⭐⭐⭐ 4-Star (6%)",  value="4star"),
            app_commands.Choice(name="⭐⭐⭐⭐⭐ 5-Star (2%)", value="5star"),
        ],
        duration=[
            app_commands.Choice(name="1 hour",    value="1h"),
            app_commands.Choice(name="6 hours",   value="6h"),
            app_commands.Choice(name="12 hours",  value="12h"),
            app_commands.Choice(name="1 day",     value="1d"),
            app_commands.Choice(name="3 days",    value="3d"),
            app_commands.Choice(name="1 week",    value="1w"),
            app_commands.Choice(name="Permanent", value="permanent"),
        ],
    )
    async def staff_add_card(
        self,
        interaction: discord.Interaction,
        idol: str,
        group: str,
        era: str,
        rarity: str,
        duration: str = "permanent",
        card_id: str = None,
        description: str = None,
        image: discord.Attachment = None,
        image_url: str = None,
    ):
        if not await owner_only(interaction):
            return

        idol = idol.strip()
        group = group.strip()
        era = era.strip()
        card_name = f"{idol} — {era}"

        # Resolve card ID
        if card_id:
            resolved_id = slugify(card_id.strip())
        else:
            resolved_id = slugify(card_name)

        if not resolved_id:
            await interaction.response.send_message(
                "Could not generate a valid card ID from those inputs.", ephemeral=True
            )
            return

        counter = 2
        base_id = resolved_id
        while resolved_id in cd.ALL_CARDS:
            resolved_id = f"{base_id}_{counter}"
            counter += 1

        emoji = RARITY_EMOJI.get(rarity, "⭐")
        desc = description.strip() if description else f"{idol} during the {era} era."

        final_image_url = None
        if image is not None:
            if not image.content_type or not image.content_type.startswith("image/"):
                await interaction.response.send_message(
                    "Attachment must be an image file.", ephemeral=True
                )
                return
            final_image_url = image.url
        elif image_url:
            final_image_url = image_url.strip()

        # Calculate expiry
        delta = DURATION_MAP.get(duration)
        expires_at: str | None = None
        if delta is not None:
            expires_at = (datetime.now(timezone.utc) + delta).isoformat()

        card_number   = await db.get_next_card_number()
        added_by_name = interaction.user.display_name
        card = {
            "id":          resolved_id,
            "name":        card_name,
            "emoji":       emoji,
            "rarity":      rarity,
            "description": desc,
            "image_url":   final_image_url,
            "idol":        idol,
            "group":       group,
            "card_number": card_number,
            "added_by":    added_by_name,
            "expires_at":  expires_at,
        }

        await db.save_custom_card(
            card_id=resolved_id, name=card_name, emoji=emoji, rarity=rarity,
            description=desc, image_url=final_image_url,
            idol_name=idol, group_name=group,
            card_number=card_number, added_by=added_by_name, expires_at=expires_at,
        )
        cd.add_card_to_pool(card, card_number=card_number)

        # Build confirmation embed
        if expires_at:
            ts = int(datetime.fromisoformat(expires_at).timestamp())
            expiry_value = f"<t:{ts}:F> (<t:{ts}:R>)"
        else:
            expiry_value = "🔁 Permanent"

        embed = discord.Embed(
            title=f"{emoji} {card_name} — Added to Drop Pool!",
            description=desc,
            color=cd.RARITY_COLORS[rarity],
        )
        embed.add_field(name="Idol",    value=idol,                     inline=True)
        embed.add_field(name="Group",   value=group,                    inline=True)
        embed.add_field(name="Era",     value=era,                      inline=True)
        embed.add_field(name="Rarity",  value=cd.RARITY_STARS[rarity], inline=True)
        embed.add_field(name="Card #",  value=f"#{card_number}",        inline=True)
        embed.add_field(name="Card ID", value=f"`{resolved_id}`",       inline=True)
        embed.add_field(name="Drops until", value=expiry_value,         inline=False)
        if final_image_url:
            embed.set_image(url=final_image_url)
        embed.set_footer(text="Now live in the drop pool!")
        await interaction.response.send_message(embed=embed)

    # ── /staff edit ──────────────────────────────────────────────
    staff_edit = app_commands.Group(name="edit", description="Edit content", parent=staff)

    @staff_edit.command(name="card", description="Update a custom card's details or re-enable dropping")
    @app_commands.describe(
        card_name="Name or #number of the custom card to edit",
        duration="Reset the drop window — use Permanent to make it drop forever again",
        era="New era / concept name (updates the card title)",
        description="New flavour text",
        idol="New idol name",
        group="New group name",
        image="New image attachment",
        image_url="Or a new image URL",
    )
    @app_commands.choices(duration=[
        app_commands.Choice(name="1 hour",    value="1h"),
        app_commands.Choice(name="6 hours",   value="6h"),
        app_commands.Choice(name="12 hours",  value="12h"),
        app_commands.Choice(name="1 day",     value="1d"),
        app_commands.Choice(name="3 days",    value="3d"),
        app_commands.Choice(name="1 week",    value="1w"),
        app_commands.Choice(name="Permanent", value="permanent"),
    ])
    async def staff_edit_card(
        self,
        interaction: discord.Interaction,
        card_name: str,
        duration: str = None,
        era: str = None,
        description: str = None,
        idol: str = None,
        group: str = None,
        image: discord.Attachment = None,
        image_url: str = None,
    ):
        if not await owner_only(interaction):
            return

        card = cd.find_card(card_name)
        if not card:
            await interaction.response.send_message(
                f"No card found matching **{card_name}**.", ephemeral=True
            )
            return
        if card["id"] in cd.CARDS:
            await interaction.response.send_message(
                f"**{card['name']}** is a built-in card — only custom cards can be edited.",
                ephemeral=True,
            )
            return

        new_idol  = idol.strip()  if idol  else card.get("idol")
        new_group = group.strip() if group else card.get("group")
        new_era   = era.strip()   if era   else None

        if new_era and new_idol:
            new_name = f"{new_idol} — {new_era}"
        elif new_era:
            new_name = new_era
        else:
            new_name = card["name"]

        new_desc      = description.strip() if description else card["description"]
        new_image_url = card.get("image_url")

        if image is not None:
            if not image.content_type or not image.content_type.startswith("image/"):
                await interaction.response.send_message(
                    "Attachment must be an image file.", ephemeral=True
                )
                return
            new_image_url = image.url
        elif image_url:
            new_image_url = image_url.strip()

        # Resolve new expiry
        if duration is not None:
            delta = DURATION_MAP.get(duration)
            new_expires_at = (
                (datetime.now(timezone.utc) + delta).isoformat() if delta else None
            )
        else:
            new_expires_at = card.get("expires_at")  # unchanged

        await db.save_custom_card(
            card_id=card["id"], name=new_name, emoji=card["emoji"], rarity=card["rarity"],
            description=new_desc, image_url=new_image_url,
            idol_name=new_idol, group_name=new_group,
            card_number=card.get("card_number", 0),
            added_by=card.get("added_by", interaction.user.display_name),
            expires_at=new_expires_at,
        )
        card.update({
            "name": new_name, "description": new_desc,
            "idol": new_idol, "group": new_group,
            "image_url": new_image_url, "expires_at": new_expires_at,
        })
        cd.ALL_CARDS[card["id"]] = card

        # Expiry line for embed
        if new_expires_at:
            ts = int(datetime.fromisoformat(new_expires_at).timestamp())
            expiry_value = f"<t:{ts}:F> (<t:{ts}:R>)"
        elif duration is not None:
            expiry_value = "🔁 Permanent — drops forever"
        else:
            expiry_value = None  # don't show if unchanged

        embed = discord.Embed(
            title=f"{card['emoji']} {new_name} — Updated!",
            description=new_desc,
            color=cd.RARITY_COLORS[card["rarity"]],
        )
        embed.add_field(name="Rarity", value=cd.RARITY_STARS[card["rarity"]], inline=True)
        if new_idol:
            embed.add_field(name="Idol",  value=new_idol,  inline=True)
        if new_group:
            embed.add_field(name="Group", value=new_group, inline=True)
        if expiry_value:
            embed.add_field(name="Drops until", value=expiry_value, inline=False)
        if new_image_url:
            embed.set_image(url=new_image_url)
        await interaction.response.send_message(embed=embed)

    # ── /staff remove ────────────────────────────────────────────
    staff_remove = app_commands.Group(name="remove", description="Remove content", parent=staff)

    @staff_remove.command(name="card", description="Remove a custom card from the drop pool")
    @app_commands.describe(card_name="Name or #number of the custom card to remove")
    async def staff_remove_card(self, interaction: discord.Interaction, card_name: str):
        if not await owner_only(interaction):
            return

        card = cd.find_card(card_name)
        if not card:
            await interaction.response.send_message(
                f"No card found matching **{card_name}**.", ephemeral=True
            )
            return
        if card["id"] in cd.CARDS:
            await interaction.response.send_message(
                f"**{card['name']}** is a built-in card and cannot be removed.", ephemeral=True
            )
            return

        removed = await db.delete_custom_card(card["id"])
        if not removed:
            await interaction.response.send_message(
                f"**{card['name']}** is not a custom card.", ephemeral=True
            )
            return

        cd.remove_card_from_pool(card["id"])
        await interaction.response.send_message(
            f"✅ Removed **{card['emoji']} {card['name']}** from the drop pool.\n"
            "Players who already own it keep their copies.",
            ephemeral=True,
        )

    # ── /staff view ───────────────────────────────────────────────
    staff_view = app_commands.Group(name="view", description="View drop pool and stats", parent=staff)

    @staff_view.command(name="cardpool", description="Browse the drop pool with optional filters")
    @app_commands.describe(
        idol="Filter by idol name (partial match, e.g. Bang Chan)",
        group="Filter by group name (partial match, e.g. Stray Kids)",
        era="Filter by era / concept (partial match, e.g. God's Menu)",
        rarity="Filter by rarity tier",
    )
    @app_commands.choices(rarity=[
        app_commands.Choice(name="⭐ 1-Star",          value="1star"),
        app_commands.Choice(name="⭐⭐ 2-Star",        value="2star"),
        app_commands.Choice(name="⭐⭐⭐ 3-Star",      value="3star"),
        app_commands.Choice(name="⭐⭐⭐⭐ 4-Star",    value="4star"),
        app_commands.Choice(name="⭐⭐⭐⭐⭐ 5-Star",  value="5star"),
    ])
    async def staff_view_cardpool(
        self,
        interaction: discord.Interaction,
        idol: str = None,
        group: str = None,
        era: str = None,
        rarity: str = None,
    ):
        if not await owner_only(interaction):
            return

        all_cards = sorted(cd.ALL_CARDS.values(), key=lambda c: c.get("card_number", 999))

        filtered = all_cards
        if idol:
            filtered = [c for c in filtered if idol.lower() in (c.get("idol") or "").lower()]
        if group:
            filtered = [c for c in filtered if group.lower() in (c.get("group") or "").lower()]
        if era:
            filtered = [c for c in filtered if era.lower() in era_of(c).lower()]
        if rarity:
            filtered = [c for c in filtered if c["rarity"] == rarity]

        filter_parts = []
        if idol:   filter_parts.append(f"Idol: {idol}")
        if group:  filter_parts.append(f"Group: {group}")
        if era:    filter_parts.append(f"Era: {era}")
        if rarity: filter_parts.append(f"Rarity: {cd.RARITY_STARS[rarity]}")
        filter_label = " · ".join(filter_parts) if filter_parts else "No filters — showing all"

        if not filtered:
            await interaction.response.send_message(
                f"🔍 No cards match those filters.\n-# {filter_label}", ephemeral=True
            )
            return

        view = CardPoolView(filtered, filter_label)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
