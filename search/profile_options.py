"""Fixed choices for the profile: foods, health goals and allergies.

Users pick from these lists instead of typing, so every choice can be matched
to our data:

* A food is a cuisine (matched on the DOHMH cuisine) or a dish (matched on
  the cuisine *or* a word in the restaurant name, e.g. Sushi -> Japanese or
  "sushi" in the name).
* A health goal has its own AI example sentences (search/health_ai.py),
  a MenuStat nutrient and a few cuisine hints (search/goal_fit.py).
* An allergy is "strong" (risky cuisines are left out of Top picks) or
  "mild" (risky cuisines only lose a little Personal fit, with a warning).

Choices are saved as comma-separated labels in the existing text fields, so
no database change is needed. Older free text is mapped with ``parse_foods``
and ``parse_allergies``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from restaurants.diet_filters import ALLERGIES as DIET_ALLERGIES


@dataclass(frozen=True)
class FoodOption:
    label: str
    cuisines: frozenset = frozenset()  # DOHMH cuisine descriptions
    words: tuple = ()  # whole words/phrases searched in the restaurant name
    kind: str = "cuisine"  # "cuisine" or "dish"

    def matches(self, cuisine, name):
        if (cuisine or "").strip() in self.cuisines:
            return True
        return bool(self.words) and bool(name_pattern(self.words).search(name or ""))


def _food(label, cuisines=(), words=(), kind="cuisine"):
    return FoodOption(label, frozenset(cuisines), tuple(words), kind)


def name_pattern(words):
    alternatives = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in words)
    return re.compile(rf"\b({alternatives})\b", re.IGNORECASE)


def name_regex(words):
    """The same pattern as text, for a Django ``name__iregex`` filter."""
    return name_pattern(words).pattern


CUISINE_OPTIONS = (
    _food("American", {"American", "New American"}),
    _food("Chinese", {"Chinese", "Chinese/Japanese", "Chinese/Cuban"}),
    _food("Japanese", {"Japanese", "Chinese/Japanese"}),
    _food("Korean", {"Korean"}),
    _food("Thai", {"Thai"}),
    _food("Vietnamese", {"Southeast Asian"}, ("vietnamese", "pho", "banh mi")),
    _food("Southeast Asian", {"Southeast Asian", "Indonesian", "Filipino"}),
    _food("Filipino", {"Filipino"}),
    _food("Indian", {"Indian", "Pakistani", "Bangladeshi"}),
    _food("Asian fusion", {"Asian/Asian Fusion", "Fusion"}),
    _food("Mexican", {"Mexican", "Tex-Mex"}),
    _food("Latin American", {"Latin American", "Peruvian", "Brazilian", "Chilean"}),
    _food("Peruvian", {"Peruvian"}),
    _food("Brazilian", {"Brazilian"}),
    _food("Caribbean", {"Caribbean"}),
    _food("Italian", {"Italian"}),
    _food("Pizza", {"Pizza"}, ("pizza", "pizzeria")),
    _food("French", {"French", "New French"}),
    _food("Spanish", {"Spanish", "Tapas", "Basque"}),
    _food("Greek", {"Greek"}),
    _food("Mediterranean", {"Mediterranean"}),
    _food(
        "Middle Eastern",
        {
            "Middle Eastern",
            "Lebanese",
            "Iranian",
            "Armenian",
            "Egyptian",
            "Moroccan",
            "Afghan",
        },
    ),
    _food("Turkish", {"Turkish"}),
    _food("African", {"African", "Ethiopian"}),
    _food("Ethiopian", {"Ethiopian"}),
    _food("Eastern European", {"Eastern European", "Russian", "Polish", "Czech"}),
    _food("German", {"German"}),
    _food("Irish and British", {"Irish", "English"}),
    _food("Kosher", {"Jewish/Kosher"}, ("kosher",)),
    _food("Seafood", {"Seafood"}, ("seafood", "oyster", "lobster")),
    _food("Steakhouse", {"Steakhouse"}, ("steakhouse",)),
    _food("Soul food", {"Soul Food"}),
    _food("Cajun and Creole", {"Cajun", "Creole", "Creole/Cajun"}),
    _food("Hawaiian", {"Hawaiian", "Polynesian"}),
    _food("Vegan", {"Vegan"}, ("vegan",)),
    _food("Vegetarian", {"Vegetarian", "Vegan"}, ("vegetarian", "vegan")),
    _food(
        "Salad",
        {"Salads", "Soups/Salads/Sandwiches", "Sandwiches/Salads/Mixed Buffet"},
        ("salad", "salads"),
    ),
    _food(
        "Sandwiches",
        {"Sandwiches", "Soups/Salads/Sandwiches", "Sandwiches/Salads/Mixed Buffet"},
        ("sandwich", "sandwiches", "deli"),
    ),
    _food("Soups", {"Soups", "Soups/Salads/Sandwiches"}, ("soup", "soups")),
    _food("Chicken", {"Chicken"}),
    _food("Burgers", {"Hamburgers"}, ("burger", "burgers")),
    _food("Hot dogs", {"Hotdogs", "Hotdogs/Pretzels"}, ("hot dog", "hot dogs")),
    _food(
        "Juice and smoothies",
        {"Juice, Smoothies, Fruit Salads"},
        ("juice", "smoothie", "smoothies"),
    ),
    _food("Coffee and tea", {"Coffee/Tea"}),
    _food("Bakery", {"Bakery Products/Desserts"}, ("bakery",)),
    _food("Desserts", {"Frozen Desserts", "Bakery Products/Desserts", "Donuts"}),
    _food("Donuts", {"Donuts"}, ("donut", "donuts", "doughnut")),
    _food("Bagels", {"Bagels/Pretzels"}, ("bagel", "bagels")),
    _food("Pancakes and waffles", {"Pancakes/Waffles"}, ("pancake", "waffle")),
)

DISH_OPTIONS = (
    _food("Sushi", {"Japanese"}, ("sushi", "omakase"), "dish"),
    _food("Ramen", (), ("ramen",), "dish"),
    _food("Pho", (), ("pho",), "dish"),
    _food("Noodles", (), ("noodle", "noodles", "ramen", "pho", "udon"), "dish"),
    _food("Dumplings", (), ("dumpling", "dumplings", "dim sum"), "dish"),
    _food("Tacos", {"Mexican", "Tex-Mex"}, ("taco", "tacos", "taqueria"), "dish"),
    _food("Burritos", (), ("burrito", "burritos"), "dish"),
    _food("BBQ", {"Barbecue"}, ("bbq", "barbecue", "smokehouse"), "dish"),
    _food("Poke", {"Hawaiian"}, ("poke",), "dish"),
    _food("Wings", (), ("wing", "wings"), "dish"),
    _food("Fried chicken", {"Chicken"}, ("fried chicken",), "dish"),
    _food("Curry", {"Indian"}, ("curry",), "dish"),
    _food("Shawarma", (), ("shawarma", "gyro", "gyros", "falafel"), "dish"),
    _food("Bubble tea", (), ("bubble tea", "boba"), "dish"),
    _food("Grain bowls", (), ("bowl", "bowls", "grain"), "dish"),
)

FOOD_OPTIONS = CUISINE_OPTIONS + DISH_OPTIONS
FOODS_BY_LABEL = {option.label.casefold(): option for option in FOOD_OPTIONS}
POPULAR_FOODS = (
    "Japanese",
    "Korean",
    "Chinese",
    "Mexican",
    "Italian",
    "Thai",
    "Indian",
    "Mediterranean",
    "Salad",
    "Sushi",
    "Burgers",
    "Vegan",
)

_FILLER = re.compile(r"\b(food|foods|cuisine|restaurants?|dishes|style)\b", re.I)


def _option_for_phrase(phrase):
    """The option for one typed phrase, trying plurals ("tacos" -> Tacos)."""
    key = " ".join(_FILLER.sub(" ", phrase).split()).casefold()
    if not key:
        return None
    for candidate in (key, key + "s", key.removesuffix("s"), key.removesuffix("es")):
        if candidate in FOODS_BY_LABEL:
            return FOODS_BY_LABEL[candidate]
    return None


def parse_foods(text):
    """(options, unknown phrases) from a saved favorite/disliked foods value.

    New values are option labels. Older free text is mapped where possible:
    "chinese food" -> Chinese; "korean bbq" -> Korean and BBQ; a phrase that
    matches nothing is returned in *unknown* (not used for scoring).
    """
    options, unknown = [], []
    for phrase in re.split(r"[,;\n]+", text or ""):
        phrase = phrase.strip()
        if not phrase:
            continue
        found = _option_for_phrase(phrase)
        if found is not None:
            found = [found]
        else:
            # Several known names inside one phrase ("korean bbq").
            found = [
                option
                for option in FOOD_OPTIONS
                if re.search(rf"\b{re.escape(option.label)}\b", phrase, re.I)
                or (option.kind == "dish" and name_pattern(option.words).search(phrase))
            ]
        if not found:
            unknown.append(phrase)
        for option in found:
            if option not in options:
                options.append(option)
    return options, unknown


def food_labels(text):
    return [option.label for option in parse_foods(text)[0]]


def first_food_match(text, cuisine, name):
    """The first chosen food that matches this restaurant, or None."""
    for option in parse_foods(text)[0]:
        if option.matches(cuisine, name):
            return option
    return None


# ---------------------------------------------------------------------------
# Health goals

HEALTH_GOALS = (
    ("weight-loss", "Weight loss", "Lighter, lower-calorie meals"),
    ("muscle-gain", "Muscle gain", "More protein"),
    ("heart-health", "Heart health", "Less salt, less fried food"),
    ("less-sugar", "Less sugar", "Fewer sweets and sugary drinks"),
    ("balanced-diet", "Balanced diet", "Veggies, protein, and grains"),
    ("low-carb", "Low carb", "Less bread, rice, and pasta"),
)
GOAL_LABELS = {key: label for key, label, _hint in HEALTH_GOALS}
GOAL_HINTS = {key: hint for key, _label, hint in HEALTH_GOALS}
# Older goal keys: "More energy" joined "Balanced diet"; "Manage a medical
# condition" was too broad to score and is dropped.
OLD_GOALS = {"more-energy": "balanced-diet", "manage-condition": None}


def normalize_goals(goals):
    """Current goal keys from a saved list (old keys mapped, unknown dropped)."""
    result = []
    for goal in goals or []:
        goal = OLD_GOALS.get(goal, goal)
        if goal in GOAL_LABELS and goal not in result:
            result.append(goal)
    return result


# ---------------------------------------------------------------------------
# Allergies

STRONG_ALLERGY_CUISINES = {
    "nuts": DIET_ALLERGIES["nuts"]["cuisines"],
    "shellfish": DIET_ALLERGIES["shellfish"]["cuisines"],
    "fish": {"Seafood", "Japanese", "Chinese/Japanese", "Hawaiian", "Polynesian"},
}
MILD_ALLERGY_CUISINES = {
    "dairy": {
        "Pizza",
        "Italian",
        "Frozen Desserts",
        "Bakery Products/Desserts",
        "Pancakes/Waffles",
        "Indian",
    },
    "gluten": {
        "Pizza",
        "Italian",
        "Bakery Products/Desserts",
        "Bagels/Pretzels",
        "Donuts",
        "Sandwiches",
        "Pancakes/Waffles",
    },
    "egg": {"Bakery Products/Desserts", "Pancakes/Waffles", "Donuts"},
    "soy": {"Japanese", "Chinese", "Korean", "Asian/Asian Fusion", "Chinese/Japanese"},
    "sesame": {
        "Middle Eastern",
        "Lebanese",
        "Korean",
        "Chinese",
        "Bagels/Pretzels",
        "Mediterranean",
    },
}
ALLERGY_OPTIONS = (
    ("nuts", "Nuts"),
    ("shellfish", "Shellfish"),
    ("fish", "Fish"),
    ("dairy", "Dairy"),
    ("gluten", "Gluten"),
    ("egg", "Egg"),
    ("soy", "Soy"),
    ("sesame", "Sesame"),
)
ALLERGY_LABELS = dict(ALLERGY_OPTIONS)
_ALLERGY_WORDS = {
    "nuts": r"peanuts?|tree\s*nuts?|nuts?|almonds?|cashews?|walnuts?",
    "shellfish": r"shellfish|shrimps?|lobsters?|crabs?|mussels?|clams?|oysters?",
    "fish": r"fish|salmon|tuna|cod",
    "dairy": r"dairy|milk|lactose|cheese",
    "gluten": r"gluten|wheat|celiac|coeliac",
    "egg": r"eggs?",
    "soy": r"soy|soya|soybeans?",
    "sesame": r"sesame",
}


def parse_allergies(text):
    """Allergy keys from a saved value (labels or older free text)."""
    text = (text or "").casefold()
    return [
        key
        for key, _label in ALLERGY_OPTIONS
        if re.search(rf"\b({_ALLERGY_WORDS[key]})\b", text)
    ]


def allergens_in(keys, text):
    """Allergy keys whose allergen word appears in *text* (a dish name)."""
    text = (text or "").casefold()
    return [key for key in keys if re.search(rf"\b({_ALLERGY_WORDS[key]})\b", text)]


def strong_allergy_cuisines(keys):
    return set().union(*(STRONG_ALLERGY_CUISINES.get(k, set()) for k in keys))


def mild_allergy_hits(keys, cuisine):
    """Mild allergies whose allergen is common in this cuisine."""
    cuisine = (cuisine or "").strip()
    return [k for k in keys if cuisine in MILD_ALLERGY_CUISINES.get(k, set())]
