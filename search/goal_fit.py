"""How well a restaurant fits the viewer's health goals (0-1 per goal).

Three sources, each optional:

1. AI review score for the goal (stored with the health score; see
   search/health_ai.GOAL_ANCHORS). Most places with reviews have it.
2. MenuStat nutrients for chains (median of the latest menu's meals), e.g.
   protein for Muscle gain or sodium for Heart health.
3. A small cuisine hint (+/-0.1), e.g. Steakhouse for Low carb.

The available sources from 1 and 2 are averaged (0.5 when there is none),
then the cuisine hint is added and the result kept between 0 and 1.
"""

from __future__ import annotations

import statistics

from search.profile_options import GOAL_LABELS

MIN_MEALS = 3
CUISINE_HINT = 0.1

# goal -> (MenuStat field, value scored 0, value scored 1, unit)
MENU_NUTRIENTS = {
    "weight-loss": ("calories", 800.0, 300.0, "kcal"),
    "muscle-gain": ("protein", 10.0, 40.0, "g protein"),
    "heart-health": ("sodium", 2000.0, 600.0, "mg sodium"),
    "less-sugar": ("sugar", 25.0, 5.0, "g sugar"),
    "balanced-diet": ("dietary_fiber", 2.0, 8.0, "g fiber"),
    "low-carb": ("carbohydrates", 90.0, 25.0, "g carbs"),
}

_SALADS = "Salads"
_SOUP_SALAD = "Soups/Salads/Sandwiches"
_JUICE = "Juice, Smoothies, Fruit Salads"
_SWEETS = {"Donuts", "Frozen Desserts", "Bakery Products/Desserts"}

# goal -> (cuisines that fit, cuisines that don't)
CUISINE_HINTS = {
    "weight-loss": (
        {_SALADS, _SOUP_SALAD, _JUICE, "Vegan", "Vegetarian", "Japanese"},
        {"Hamburgers", "Pizza", "Chicken", "Pancakes/Waffles"} | _SWEETS,
    ),
    "muscle-gain": (
        {
            "Steakhouse",
            "Barbecue",
            "Chicken",
            "Korean",
            "Brazilian",
            "Seafood",
            "Middle Eastern",
            "Greek",
        },
        {_JUICE, "Coffee/Tea"} | _SWEETS,
    ),
    "heart-health": (
        {"Mediterranean", "Greek", "Seafood", "Japanese", _SALADS, "Vegan"},
        {"Hamburgers", "Hotdogs", "Chicken", "Pizza", "Soul Food", "Barbecue"},
    ),
    "less-sugar": (
        {"Steakhouse", "Seafood", "Mediterranean", _SALADS},
        {_JUICE, "Pancakes/Waffles", "Coffee/Tea", "Nuts/Confectionary"} | _SWEETS,
    ),
    "balanced-diet": (
        {
            "Mediterranean",
            "Japanese",
            "Korean",
            "Greek",
            "Middle Eastern",
            _SALADS,
            _SOUP_SALAD,
        },
        {"Hotdogs", "Hamburgers"} | _SWEETS,
    ),
    "low-carb": (
        {"Steakhouse", "Barbecue", "Seafood", "Brazilian", "Greek", _SALADS},
        {
            "Pizza",
            "Italian",
            "Bagels/Pretzels",
            "Sandwiches",
            "Pancakes/Waffles",
        }
        | _SWEETS,
    ),
}


def _linear(value, zero_at, one_at):
    return max(0.0, min(1.0, (value - zero_at) / (one_at - zero_at)))


def menu_nutrients(name):
    """{field: median} over the latest MenuStat meals of a chain, or {}."""
    # Imported here so the scoring math above stays free of database code.
    from django.db.models import Max

    from search.menustat import MEAL_CATEGORIES, match_menustat_restaurant
    from search.models import MenuItem

    chain = match_menustat_restaurant(name)
    if not chain:
        return {}
    latest = MenuItem.objects.filter(restaurant=chain).aggregate(y=Max("year"))["y"]
    fields = sorted({spec[0] for spec in MENU_NUTRIENTS.values()})
    rows = MenuItem.objects.filter(
        restaurant=chain,
        year=latest,
        food_category__in=MEAL_CATEGORIES,
        kids_meal=False,
    ).values_list(*fields)
    medians = {}
    for index, field in enumerate(fields):
        values = [float(row[index]) for row in rows if row[index] is not None]
        if len(values) >= MIN_MEALS:
            medians[field] = statistics.median(values)
    return medians


def goal_fit(goal, cuisine="", ai_goal=None, nutrients=None):
    """(fit 0-1, steps) for one goal. ``nutrients`` is from menu_nutrients."""
    steps, sources = [], []
    if ai_goal is not None:
        sources.append(float(ai_goal))
        steps.append(("AI review score (MiniLM)", f"{float(ai_goal):.2f}"))
    spec = MENU_NUTRIENTS.get(goal)
    if spec and nutrients and spec[0] in nutrients:
        field, zero_at, one_at, unit = spec
        menu = _linear(nutrients[field], zero_at, one_at)
        sources.append(menu)
        steps.append((f"MenuStat meals: {nutrients[field]:.0f} {unit}", f"{menu:.2f}"))
    base = sum(sources) / len(sources) if sources else 0.5
    if not sources:
        steps.append(("No reviews or menu to read", "0.50"))
    elif len(sources) > 1:
        steps.append(("Average", f"{base:.2f}"))
    good, bad = CUISINE_HINTS.get(goal, (set(), set()))
    cuisine = (cuisine or "").strip()
    hint = CUISINE_HINT if cuisine in good else -CUISINE_HINT if cuisine in bad else 0
    if hint:
        steps.append((f"Cuisine ({cuisine})", f"{hint:+.2f}"))
    fit = max(0.0, min(1.0, base + hint))
    return fit, steps


def goals_fit(goals, cuisine="", ai_goals=None, nutrients=None):
    """(average fit 0-1, [(goal label, fit, steps)]) or (None, []) without goals."""
    details = []
    for goal in goals:
        fit, steps = goal_fit(goal, cuisine, (ai_goals or {}).get(goal), nutrients)
        details.append((GOAL_LABELS.get(goal, goal), fit, steps))
    if not details:
        return None, []
    return sum(fit for _label, fit, _steps in details) / len(details), details
