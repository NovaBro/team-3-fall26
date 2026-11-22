"""Personalized Top Picks (#129).

Django picks a shortlist that leans toward the user's favorites and home
borough, then Claude orders it, judging allergies itself. Results are cached
because this runs while the home page loads. Any failure returns [] so the page
falls back to the normal picks.
"""

import hashlib
import json
import logging
import re
from textwrap import shorten

import anthropic
from django.conf import settings
from django.core.cache import cache
from django.db.models import F

from assistant.llm import get_client, is_configured
from assistant.profile import has_preferences, preferences, render_context
from assistant.prompts import RERANK_SYSTEM_PROMPT
from assistant.tools import available_cuisines, display_text
from search.find_food import restaurant_item, restaurant_rows

logger = logging.getLogger(__name__)

SHORTLIST_SIZE = 30
GENERAL_SLOTS = 10
MIN_LOCAL_CANDIDATES = 10
MAX_REASON_CHARS = 200
CACHE_SECONDS = 6 * 60 * 60
FAILURE_CACHE_SECONDS = 5 * 60
RANK_TIMEOUT_SECONDS = 15.0
MIN_RATING = 4.0  # candidates Claude chooses from

# Foods people write that aren't cuisine labels.
FOOD_HINTS = {
    "burger": ["Hamburgers"],
    "curry": ["Indian", "Thai"],
    "dumpling": ["Chinese"],
    "fast food": ["Hamburgers", "Chicken"],
    "noodle": ["Japanese", "Chinese", "Southeast Asian"],
    "pasta": ["Italian"],
    "pho": ["Southeast Asian"],
    "ramen": ["Japanese"],
    "salad": ["Salads"],
    "sushi": ["Japanese"],
    "taco": ["Mexican"],
}

RANK_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["key", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ranked"],
    "additionalProperties": False,
}


def _contains_word(text, phrase):
    return re.search(rf"\b{re.escape(phrase)}(s|es)?\b", text, re.IGNORECASE)


def matching_cuisines(text, cuisines):
    """Cuisine labels mentioned in free text such as "Italian, ramen"."""
    if not text:
        return set()
    found = {
        cuisine
        for cuisine in cuisines
        if any(_contains_word(text, part.strip()) for part in cuisine.split("/"))
    }
    for food, hinted in FOOD_HINTS.items():
        if _contains_word(text, food):
            found.update(name for name in hinted if name in cuisines)
    return found


def _best_rated(blocked, limit, include=None, borough=""):
    """Open, well-rated restaurants, best Google rating first."""
    rows = restaurant_rows({}).filter(rating__gte=MIN_RATING)
    if include:
        rows = rows.filter(cuisine__in=include)
    if borough:
        rows = rows.filter(boro=borough)
    rows = rows.exclude(cuisine__in=blocked)
    return list(
        rows.order_by(
            F("rating").desc(), F("rating_count").desc(nulls_last=True), "place_id"
        )[:limit]
    )


def _shortlist_in(prefs, size, borough):
    cuisines = available_cuisines()
    blocked = matching_cuisines(prefs["disliked_foods"], cuisines)
    favorites = matching_cuisines(prefs["favorite_foods"], cuisines)
    favorites = sorted(favorites - blocked)

    rows = []
    if favorites:
        each = max(1, (size - GENERAL_SLOTS) // len(favorites))
        for cuisine in favorites:
            rows += _best_rated(blocked, each, [cuisine], borough)
    rows += _best_rated(blocked, GENERAL_SLOTS * 2, None, borough)

    items = {}
    for row in rows:
        items.setdefault(row["place_id"], restaurant_item(row))
    return list(items.values())[:size]


def shortlist(prefs, size=SHORTLIST_SIZE):
    """Well-rated places near home if we know the borough, weighted toward
    favorites.

    Only disliked cuisines are left out. Claude weighs allergies when ranking.
    """
    borough = prefs["home_area"]["borough"]
    if borough:
        items = _shortlist_in(prefs, size, borough)
        if len(items) >= MIN_LOCAL_CANDIDATES:
            return items
    return _shortlist_in(prefs, size, "")


def _candidate_json(items):
    candidates = []
    for item in items:
        candidate = {
            "key": item["key"],
            "name": display_text(item["name"]),
            "cuisine": item["details"][0] if item["details"] else "",
            "borough": display_text(item["borough"]),
        }
        if item["rating"] is not None:
            candidate["google_rating"] = item["rating"]
            candidate["google_rating_count"] = item["rating_count"]
        if item["price"]:
            candidate["price"] = item["price"]
        candidates.append(candidate)
    return json.dumps(candidates)


def rank_with_llm(prefs, items, count):
    """Return [{"place_id", "reason"}], best first, padded from *items* if short."""
    # This runs during a page load, so fail fast and show the normal picks instead.
    client = get_client(timeout=RANK_TIMEOUT_SECONDS, max_retries=0)
    response = client.messages.create(
        model=settings.ASSISTANT_MODEL,
        max_tokens=3000,
        system=RERANK_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Pick and order the best {count} places for this user.\n\n"
                    f"{render_context(prefs)}\n\n"
                    f"<candidates>{_candidate_json(items)}</candidates>"
                ),
            }
        ],
        # Ranking is simple and blocks a page load, so skip thinking to save time.
        thinking={"type": "disabled"},
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": RANK_SCHEMA},
        },
    )
    if response.stop_reason != "end_turn":
        raise ValueError(f"Unexpected stop reason: {response.stop_reason}")
    text = next(block.text for block in response.content if block.type == "text")
    ranked = json.loads(text)["ranked"]

    allowed = {item["key"] for item in items}
    picks = {}
    for entry in ranked:
        if entry["key"] in allowed and entry["key"] not in picks:
            picks[entry["key"]] = shorten(entry["reason"], MAX_REASON_CHARS)
    if not picks:
        raise ValueError("The ranking didn't include any candidates.")
    for item in items:
        if len(picks) >= count:
            break
        picks.setdefault(item["key"], "")
    return [
        {"place_id": key.split(":", 1)[1], "reason": reason}
        for key, reason in list(picks.items())[:count]
    ]


def _cache_key(user, prefs, count):
    fingerprint = json.dumps(
        [settings.ASSISTANT_MODEL, count, prefs], sort_keys=True
    ).encode()
    return f"assistant:picks:{user.id}:{hashlib.sha256(fingerprint).hexdigest()}"


def personalized_picks(user, count=3):
    """Top Picks for this user: [{"place_id", "reason"}], or [] for the defaults."""
    if not is_configured() or not user.is_authenticated:
        return []
    prefs = preferences(user)
    if not has_preferences(prefs):
        return []
    key = _cache_key(user, prefs, count)
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        items = shortlist(prefs)
        if not items:
            raise ValueError("No candidates matched this profile.")
        picks = rank_with_llm(prefs, items, count)
    except (anthropic.APIError, ValueError, KeyError, TypeError, StopIteration):
        logger.warning("Personalized picks failed", exc_info=True)
        cache.set(key, [], FAILURE_CACHE_SECONDS)
        return []
    cache.set(key, picks, CACHE_SECONDS)
    return picks
