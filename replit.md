# Bang Chan Bot

A Discord K-pop photocard bot themed around Bang Chan from Stray Kids. Players claim photocards from drops, build binders, trade, and run a live coin economy.

## Run & Operate

- `cd discord-bot && python bot.py` — run the bot (managed by the "Discord Card Bot" workflow)
- Required secret: `DISCORD_BOT_TOKEN` — Discord bot token from the Developer Portal

## Stack

- Python 3.11
- discord.py 2.x (slash commands via `app_commands`)
- aiosqlite (async SQLite)
- SQLite database stored at `discord-bot/cardbot.db`

## Where things live

- `discord-bot/bot.py` — entry point, bot class, extension loading
- `discord-bot/cards_data.py` — all card definitions, rarities, drop weights
- `discord-bot/database.py` — all DB queries (users, cards, shop listings)
- `discord-bot/cogs/cards_cog.py` — `/drop`, `/inventory`, `/card`, `/search`, `/cards`, `/profile`
- `discord-bot/cogs/shop_cog.py` — `/shop`, `/buy`, `/delist`, `/gift`
- `discord-bot/cogs/trade_cog.py` — `/trade`
- `discord-bot/cogs/admin_cog.py` — `/addcard`, `/editcard`, `/removecard`, `/cardpool`

## Commands

| Command | Description |
|---------|-------------|
| `/drop` | Drop 3 photocards — first to click a number claims it (30s channel cooldown) |
| `/inventory [user]` | Browse your photocard binder — one card per page, sort by rarity/idol/name, Sell button built in |
| `/card <name or #N>` | View details about a specific photocard |
| `/search <query>` | Search all cards by name, idol, or group |
| `/cards` | Full photocard index grouped by star rating |
| `/profile [user]` | View a STAY's collection stats, bias cards, rarest pull, gift history |
| `/trade @user <your_card> <their_card>` | Propose a card trade (2-minute window) |
| `/shop` | Browse all cards currently for sale |
| `/buy <listing_id>` | Buy a card from the shop |
| `/delist <listing_id>` | Remove your own shop listing |
| `/gift @user <card>` | Send a photocard gift — recipient must accept |
| `/addcard` | [Admin] Add a custom photocard with image upload |
| `/editcard` | [Admin] Edit a custom card's details or image |
| `/removecard` | [Admin] Remove a custom card from the pool |
| `/cardpool` | [Admin] View all cards in the drop pool |

## Cards

No built-in cards — all cards are managed via `/staff add card`. The drop pool starts empty and is fully staff-curated.

## Economy

- Users start with 100 coins
- Sell cards via the **Sell button** inside `/inventory` (non-5-star only)
- Spend coins to `/buy` cards from the shop
- 5-star cards can only be obtained through drops, trades, or gifts

## Architecture decisions

- Slash commands via `discord.app_commands` — no prefix commands needed
- aiosqlite for non-blocking DB in asyncio event loop
- In-memory Views for drops and trades (no DB state for pending interactions)
- Card instances tracked by row ID — allows multiple copies of the same card
- Shop listings lock the card instance (excluded from trade/gift while listed)
- Drop embeds share a URL so Discord renders 3 card images as a side-by-side gallery
- Inventory is one-card-per-page with inline Sell modal (replaces `/sell` slash command)

## Gotchas

- Slash commands require the bot to be invited with `applications.commands` scope
- The bot must be re-invited if new slash commands are added (or guild-sync manually)
- `cardbot.db` is created automatically on first run
- 5-star cards block the Sell button automatically

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._
