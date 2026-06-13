import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent / "cardbot.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                coins INTEGER DEFAULT 100
            );

            CREATE TABLE IF NOT EXISTS user_cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                card_id TEXT NOT NULL,
                obtained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS shop_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id TEXT NOT NULL,
                seller_name TEXT NOT NULL,
                user_card_id INTEGER NOT NULL,
                card_id TEXT NOT NULL,
                price INTEGER NOT NULL,
                listed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (seller_id) REFERENCES users(user_id),
                FOREIGN KEY (user_card_id) REFERENCES user_cards(id)
            );

            CREATE TABLE IF NOT EXISTS custom_cards (
                card_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '🃏',
                rarity TEXT NOT NULL DEFAULT 'common',
                description TEXT NOT NULL DEFAULT '',
                image_url TEXT,
                idol_name TEXT,
                group_name TEXT,
                card_number INTEGER,
                added_by TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS gift_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT NOT NULL,
                sender_name TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                recipient_name TEXT NOT NULL,
                card_id TEXT NOT NULL,
                card_name TEXT NOT NULL,
                gifted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS card_number_counter (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                next_number INTEGER NOT NULL DEFAULT 19
            );

            INSERT OR IGNORE INTO card_number_counter (id, next_number) VALUES (1, 1);
        """)
        # Migrate existing tables — add columns that may not exist yet
        migrations = [
            "ALTER TABLE custom_cards ADD COLUMN idol_name TEXT",
            "ALTER TABLE custom_cards ADD COLUMN group_name TEXT",
            "ALTER TABLE custom_cards ADD COLUMN card_number INTEGER",
            "ALTER TABLE custom_cards ADD COLUMN expires_at TEXT",
            # Reset counter to 1 if it was the old built-in default (≤19)
            "UPDATE card_number_counter SET next_number = 1 WHERE id = 1 AND next_number <= 19",
        ]
        for sql in migrations:
            try:
                await db.execute(sql)
            except Exception:
                pass
        await db.commit()


async def get_next_card_number() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT next_number FROM card_number_counter WHERE id = 1") as cur:
            row = await cur.fetchone()
            n = row[0] if row else 19
        await db.execute("UPDATE card_number_counter SET next_number = ? WHERE id = 1", (n + 1,))
        await db.commit()
        return n


async def ensure_user(user_id: str, username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, coins) VALUES (?, ?, 100)",
            (user_id, username),
        )
        await db.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        await db.commit()


async def get_user(user_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_coins(user_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def add_coins(user_id: str, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()


async def spend_coins(user_id: str, amount: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        if not row or row[0] < amount:
            return False
        await db.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, user_id))
        await db.commit()
        return True


async def add_card_to_user(user_id: str, card_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (user_id, card_id)
        )
        await db.commit()
        return cur.lastrowid


async def get_user_cards(user_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_cards WHERE user_id = ? ORDER BY obtained_at DESC", (user_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_card_instance(instance_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM user_cards WHERE id = ?", (instance_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def find_user_card_instance(user_id: str, card_id: str) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT uc.id FROM user_cards uc
               WHERE uc.user_id = ? AND uc.card_id = ?
               AND uc.id NOT IN (SELECT user_card_id FROM shop_listings)
               ORDER BY uc.obtained_at ASC LIMIT 1""",
            (user_id, card_id),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def transfer_card(instance_id: int, new_owner_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_cards SET user_id = ? WHERE id = ?", (new_owner_id, instance_id))
        await db.commit()


async def remove_card_instance(instance_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_cards WHERE id = ?", (instance_id,))
        await db.commit()


async def create_listing(seller_id: str, seller_name: str, user_card_id: int, card_id: str, price: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO shop_listings (seller_id, seller_name, user_card_id, card_id, price) VALUES (?, ?, ?, ?, ?)",
            (seller_id, seller_name, user_card_id, card_id, price),
        )
        await db.commit()
        return cur.lastrowid


async def get_listings() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM shop_listings ORDER BY listed_at DESC") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_listing(listing_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM shop_listings WHERE id = ?", (listing_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def remove_listing(listing_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM shop_listings WHERE id = ?", (listing_id,))
        await db.commit()


async def get_user_listings(user_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM shop_listings WHERE seller_id = ?", (user_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def save_custom_card(card_id: str, name: str, emoji: str, rarity: str, description: str,
                           image_url: str | None, idol_name: str | None, group_name: str | None,
                           card_number: int, added_by: str, expires_at: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO custom_cards
               (card_id, name, emoji, rarity, description, image_url, idol_name, group_name,
                card_number, added_by, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (card_id, name, emoji, rarity, description, image_url, idol_name, group_name,
             card_number, added_by, expires_at),
        )
        await db.commit()


async def delete_custom_card(card_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM custom_cards WHERE card_id = ?", (card_id,))
        await db.commit()
        return cur.rowcount > 0


async def get_custom_cards() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM custom_cards ORDER BY card_number ASC") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def log_gift(sender_id: str, sender_name: str, recipient_id: str,
                   recipient_name: str, card_id: str, card_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO gift_history (sender_id, sender_name, recipient_id, recipient_name, card_id, card_name)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sender_id, sender_name, recipient_id, recipient_name, card_id, card_name),
        )
        await db.commit()


async def get_gift_history(user_id: str, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM gift_history
               WHERE sender_id = ? OR recipient_id = ?
               ORDER BY gifted_at DESC LIMIT ?""",
            (user_id, user_id, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_collection_stats(user_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = ?", (user_id,)) as cur:
            total = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(DISTINCT card_id) FROM user_cards WHERE user_id = ?", (user_id,)
        ) as cur:
            unique = (await cur.fetchone())[0]
        async with db.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            coins = row[0] if row else 0
        async with db.execute(
            "SELECT card_id, COUNT(*) as cnt FROM user_cards WHERE user_id = ? GROUP BY card_id",
            (user_id,),
        ) as cur:
            card_counts = {r[0]: r[1] for r in await cur.fetchall()}
        async with db.execute(
            "SELECT COUNT(*) FROM gift_history WHERE sender_id = ?", (user_id,)
        ) as cur:
            gifts_sent = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM gift_history WHERE recipient_id = ?", (user_id,)
        ) as cur:
            gifts_received = (await cur.fetchone())[0]
    return {
        "total": total, "unique": unique, "coins": coins,
        "card_counts": card_counts, "gifts_sent": gifts_sent, "gifts_received": gifts_received,
    }
