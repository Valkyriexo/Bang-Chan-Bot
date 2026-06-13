import random
from datetime import datetime, timezone

RARITY_COLORS = {
    "1star": 0x9e9e9e,
    "2star": 0x4caf50,
    "3star": 0x2196f3,
    "4star": 0xab47bc,
    "5star": 0xffd700,
}

RARITY_STARS = {
    "1star": "⭐ 1-Star",
    "2star": "⭐⭐ 2-Star",
    "3star": "⭐⭐⭐ 3-Star",
    "4star": "⭐⭐⭐⭐ 4-Star",
    "5star": "⭐⭐⭐⭐⭐ 5-Star",
}

RARITY_WEIGHTS = {
    "1star": 55,
    "2star": 25,
    "3star": 12,
    "4star": 6,
    "5star": 2,
}

RARITY_ORDER = ["5star", "4star", "3star", "2star", "1star"]

# Legacy mapping for any custom cards stored with old rarity names
RARITY_LEGACY = {
    "common": "1star",
    "uncommon": "2star",
    "rare": "3star",
    "legendary": "5star",
}

# No built-in cards — all cards are added via /staff add card
CARDS: dict[str, dict] = {}

ALL_CARDS: dict[str, dict] = {}
_next_custom_number = 1


def normalise_rarity(rarity: str) -> str:
    return RARITY_LEGACY.get(rarity, rarity)


def add_card_to_pool(card: dict, card_number: int = None):
    global _next_custom_number
    card["rarity"] = normalise_rarity(card.get("rarity", "1star"))
    if card_number is not None:
        card["card_number"] = card_number
    elif "card_number" not in card:
        card["card_number"] = _next_custom_number
        _next_custom_number += 1
    ALL_CARDS[card["id"]] = card


def remove_card_from_pool(card_id: str):
    ALL_CARDS.pop(card_id, None)


def get_card_by_number(number: int) -> dict | None:
    for card in ALL_CARDS.values():
        if card.get("card_number") == number:
            return card
    return None


def is_expired(card: dict) -> bool:
    exp = card.get("expires_at")
    if not exp:
        return False
    try:
        dt = datetime.fromisoformat(exp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt < datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def get_random_card() -> dict | None:
    active = [c for c in ALL_CARDS.values() if not is_expired(c)]
    if not active:
        return None
    rarities = list(RARITY_WEIGHTS.keys())
    weights = [RARITY_WEIGHTS[r] for r in rarities]
    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]
    pool = [c for c in active if c["rarity"] == chosen_rarity]
    if not pool:
        pool = active
    return random.choice(pool)


def find_card(query: str) -> dict | None:
    q = query.strip()
    if q.startswith("#") and q[1:].isdigit():
        return get_card_by_number(int(q[1:]))
    if q.isdigit():
        return get_card_by_number(int(q))
    q_lower = q.lower()
    for card in ALL_CARDS.values():
        if card["name"].lower() == q_lower or card["id"] == q_lower.replace(" ", "_"):
            return card
    for card in ALL_CARDS.values():
        if q_lower in card["name"].lower():
            return card
    return None
