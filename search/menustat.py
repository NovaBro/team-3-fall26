"""MenuStat helpers: fuzzy restaurant match, qualifying meals, calorie stats.

Linking is by normalized restaurant *name*, not CAMIS. Menus are historical
(often 2017–2018) and may not match today's offerings.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from functools import lru_cache

from django.db.models import Max

from search.models import MenuItem

MEAL_CATEGORIES = frozenset(
    {
        "Entrees",
        "Sandwiches",
        "Salads",
        "Burgers",
        "Pizza",
        "Soup",
    }
)
MIN_PROTEIN_G = 15.0
MIN_MEALS_FOR_SCORE = 3
CALORIE_SCORE_HIGH_KCAL = 200.0  # → 1.0
CALORIE_SCORE_LOW_KCAL = 800.0  # → 0.0


def normalize_name(value):
    """Casefold and strip punctuation/diacritics for fuzzy name matching."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


@lru_cache(maxsize=1)
def _menustat_restaurant_index():
    """Map normalized MenuStat restaurant name → canonical display name."""
    names = (
        MenuItem.objects.exclude(restaurant="")
        .values_list("restaurant", flat=True)
        .distinct()
    )
    index = {}
    for name in names:
        key = normalize_name(name)
        if key and key not in index:
            index[key] = name
    return index


def clear_menustat_cache():
    """Drop cached restaurant index (tests / after re-import)."""
    _menustat_restaurant_index.cache_clear()


def match_menustat_restaurant(name):
    """Fuzzy-match an inspection/Google name to a MenuStat restaurant label.

    Exact normalized match first; otherwise a single unambiguous prefix or
    contains hit. Returns the MenuStat ``restaurant`` string, or None.
    """
    key = normalize_name(name)
    if not key:
        return None
    index = _menustat_restaurant_index()
    if key in index:
        return index[key]

    # Prefix: "mcdonalds 123" ↔ "mcdonalds", or "burger king midtown" ↔ "burger king".
    prefix_hits = [
        display
        for norm, display in index.items()
        if norm.startswith(key + " ") or key.startswith(norm + " ")
    ]
    unique_prefix = list(dict.fromkeys(prefix_hits))
    if len(unique_prefix) == 1:
        return unique_prefix[0]

    contains_hits = [
        display for norm, display in index.items() if key in norm or norm in key
    ]
    unique_contains = list(dict.fromkeys(contains_hits))
    if len(unique_contains) == 1:
        return unique_contains[0]
    return None


def qualifying_meals(restaurant_name):
    """Return deduplicated qualifying meal rows for a MenuStat restaurant name.

    Filters: meal categories, protein ≥ 15 g, not kids' meal, calories present,
    latest year for that restaurant. One row per item_name (lowest calories).
    """
    if not restaurant_name:
        return []
    years = MenuItem.objects.filter(restaurant=restaurant_name).aggregate(
        latest=Max("year")
    )
    latest = years["latest"]
    if latest is None:
        return []

    rows = (
        MenuItem.objects.filter(
            restaurant=restaurant_name,
            year=latest,
            food_category__in=MEAL_CATEGORIES,
            kids_meal=False,
            calories__isnull=False,
            protein__gte=MIN_PROTEIN_G,
        )
        .exclude(item_name="")
        .order_by("item_name", "calories")
    )
    by_name = {}
    for row in rows:
        if row.item_name not in by_name:
            by_name[row.item_name] = row
    return list(by_name.values())


def median_meal_calories(restaurant_name):
    """Median calories among qualifying meals, or None if too few meals."""
    meals = qualifying_meals(restaurant_name)
    if len(meals) < MIN_MEALS_FOR_SCORE:
        return None
    return statistics.median(float(m.calories) for m in meals)


def calorie_score_from_median(median):
    """Map median kcal to [0, 1]: 200 → 1.0, 800 → 0.0."""
    if median is None:
        return None
    try:
        value = float(median)
    except (TypeError, ValueError):
        return None
    span = CALORIE_SCORE_LOW_KCAL - CALORIE_SCORE_HIGH_KCAL
    return max(0.0, min(1.0, (CALORIE_SCORE_LOW_KCAL - value) / span))


def calorie_score_for_name(name):
    """Resolve fuzzy match → median → score, or None if unlinked/insufficient."""
    matched = match_menustat_restaurant(name)
    if not matched:
        return None
    return calorie_score_from_median(median_meal_calories(matched))


def top_low_calorie_meals(name, limit=5):
    """Top-*limit* lowest-calorie qualifying meals for a fuzzy-matched name."""
    matched = match_menustat_restaurant(name)
    if not matched:
        return [], None
    meals = qualifying_meals(matched)
    meals.sort(key=lambda m: (m.calories is None, m.calories or 0, m.item_name))
    return meals[:limit], matched
