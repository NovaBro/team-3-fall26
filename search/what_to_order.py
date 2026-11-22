"""What to order: the restaurant's menu, and (later) dish picks from it.

Where the menu comes from:

1. MenuStat (chains in our DB): read from our own table, no API cost.
2. Otherwise the restaurant's Google photos: up to 10 photos are downloaded
   and one Gemini call finds the menu photos and reads the dish names.
Nothing from step 2 is saved in the database: Google's terms don't allow
storing Places content (only place IDs). The menu read from the photos is
kept in the cache for PLACES_CACHE_SECONDS (1 hour), the same as Google
search results, so reloading shows the same menu and costs nothing.

The page shows the whole menu, grouped into food, drinks and desserts, and
highlights a few food picks above it (never removing anything from the
list). ``score_dishes`` gives each dish a MiniLM health score and goal
scores; ``pick`` chooses from the healthy dishes (health >= HEALTHY_AT),
leaving out dishes that list one of the user's allergens and ranking down
dishes they dislike. Small menus get fewer or no picks (``pick_count``).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.core.cache import cache
from django.db.models import Max

from search import health_ai
from search.menustat import match_menustat_restaurant
from search.profile_options import (
    GOAL_LABELS,
    allergen_words_in,
    name_pattern,
    normalize_goals,
    parse_allergies,
    parse_foods,
)

logger = logging.getLogger(__name__)

PLACES_URL = "https://places.googleapis.com/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_PAUSE_KEY = "gemini-paused"  # shared with the reason paragraphs
GEMINI_PAUSE_SECONDS = 600
MAX_PHOTOS = 10
PHOTO_WIDTH = 800
GOOGLE_TIMEOUT = 8
GEMINI_TIMEOUT = 40
MAX_DISHES = 150
PICKS = 3
MIN_ITEMS_FOR_SHARE = 10
HEALTHY_AT = 0.6
GOAL_FITS_AT = 0.6
LIKE_BONUS = 0.1
DISLIKE_PENALTY = 0.15  # disliked dishes are ranked down, not removed
CALORIE_WEIGHT = 0.1  # weight loss: lower calories within this menu rank higher

READ_PROMPT = (
    "These are photos of one restaurant. Find the photos that show a menu "
    "(printed menu, menu board or menu page; not just a plate of food) and "
    "list every item you can read on all of them, drinks included. Skip "
    "words cut off at the photo "
    "edge. For each item give its name exactly as written (without the "
    "price), its description if one is printed, its price as printed (like "
    '"$12.95") or "", its calories as a number if printed or null, and a '
    'kind: "food", "drink" (coffee, tea, juices, smoothies, shakes, shots, '
    'sodas), "dessert" or "header" (section titles like APPETIZERS). Reply '
    "ONLY with JSON: "
    '{"items": [{"name": "...", "description": "...", "price": "$12.95", '
    '"calories": 450, "kind": "food"}]}. '
    'If no photo shows a menu, reply {"items": []}.'
)


KINDS = (("food", "Food"), ("drink", "Drinks"), ("dessert", "Desserts"))
MENUSTAT_KINDS = {
    "Beverages": "drink",
    "Desserts": "dessert",
    "Baked Goods": "dessert",
    "Toppings & Ingredients": None,  # not dishes
}
GROUP_PREVIEW = 10  # dishes shown per group before "Show all"


@dataclass
class Dish:
    name: str
    description: str = ""
    kind: str = "food"
    price: str = ""
    calories: int | None = None
    health: float | None = None
    goals: dict = field(default_factory=dict)
    rank: float = 0.0
    notes: list = field(default_factory=list)
    picked: bool = False  # highlighted in the menu list

    @property
    def text(self):
        return f"{self.name}. {self.description}".strip(". ")


@dataclass
class Group:
    label: str
    dishes: list

    @property
    def preview(self):
        return self.dishes[:GROUP_PREVIEW]

    @property
    def rest(self):
        return self.dishes[GROUP_PREVIEW:]


@dataclass
class Result:
    source: str = ""  # "menustat", "photos" or "" (no menu)
    groups: list = field(default_factory=list)
    picks: list = field(default_factory=list)
    skipped: list = field(default_factory=list)  # [(dish name, [allergen words])]
    goal_labels: list = field(default_factory=list)  # the user's goals, for the box
    scored: int = 0
    healthy: int = 0
    message: str = ""

    @property
    def show_share(self):
        return self.scored >= MIN_ITEMS_FOR_SHARE


# ---------------------------------------------------------------------------
# Getting the menu


def menustat_dishes(name):
    """Menu of a MenuStat chain (latest year), or []."""
    from search.models import MenuItem

    chain = match_menustat_restaurant(name)
    if not chain:
        return []
    latest = MenuItem.objects.filter(restaurant=chain).aggregate(y=Max("year"))["y"]
    rows = (
        MenuItem.objects.filter(restaurant=chain, year=latest)
        .order_by("food_category", "item_name")
        .values_list("item_name", "item_description", "food_category", "calories")
    )
    dishes = []
    for item, desc, category, calories in rows:
        kind = MENUSTAT_KINDS.get(category, "food")
        if kind:
            dishes.append(
                Dish(item or "", desc or "", kind, calories=_calories(calories))
            )
    return clean(dishes)


def _google_key():
    return os.environ.get("GOOGLE_API_KEY", "") or settings.GOOGLE_PLACES_API_KEY


def photo_names(place, query):
    """Up to MAX_PHOTOS fresh photo names for a place (by place ID if we have it)."""
    key = _google_key()
    headers = {"X-Goog-Api-Key": key}
    place_id = getattr(place, "place_id", "") if place is not None else ""
    if place_id:
        resp = requests.get(
            f"{PLACES_URL}/places/{place_id}",
            headers={**headers, "X-Goog-FieldMask": "photos"},
            timeout=GOOGLE_TIMEOUT,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos") or []
    else:
        resp = requests.post(
            f"{PLACES_URL}/places:searchText",
            json={"textQuery": query, "maxResultCount": 1},
            headers={**headers, "X-Goog-FieldMask": "places.photos"},
            timeout=GOOGLE_TIMEOUT,
        )
        resp.raise_for_status()
        places = resp.json().get("places") or []
        photos = (places[0].get("photos") if places else None) or []
    return [p["name"] for p in photos if p.get("name")][:MAX_PHOTOS]


def _download(photo_name):
    try:
        resp = requests.get(
            f"{PLACES_URL}/{photo_name}/media",
            params={"maxWidthPx": PHOTO_WIDTH, "key": _google_key()},
            timeout=GOOGLE_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return None
    mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0]
    return mime, resp.content


def download_photos(names):
    """(mime, bytes) for each photo that downloaded, in parallel."""
    if not names:
        return []
    with ThreadPoolExecutor(max_workers=min(len(names), MAX_PHOTOS)) as pool:
        return [image for image in pool.map(_download, names) if image]


class GeminiQuota(Exception):
    pass


def read_menu(images):
    """Items Gemini reads from the menu photos: [{"name", "description", "kind"}]."""
    parts = [{"text": READ_PROMPT}]
    for mime, data in images:
        encoded = base64.b64encode(data).decode()
        parts.append({"inline_data": {"mime_type": mime, "data": encoded}})
    resp = requests.post(
        f"{GEMINI_URL}/{settings.GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": settings.GEMINI_API_KEY},
        json={
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0,  # read the same menu the same way each visit
            },
        },
        timeout=GEMINI_TIMEOUT,
    )
    if resp.status_code in (402, 429):
        raise GeminiQuota(resp.text[:200])
    resp.raise_for_status()
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    answer = json.loads(text)
    items = answer.get("items") if isinstance(answer, dict) else answer
    return [item for item in items or [] if isinstance(item, dict)]


def _dishes_from(items):
    kinds = {kind for kind, _label in KINDS}
    dishes = []
    for item in items:
        kind = str(item.get("kind") or "").lower()
        if kind in kinds:  # headers and anything else are dropped
            dishes.append(
                Dish(
                    str(item.get("name") or ""),
                    str(item.get("description") or ""),
                    kind,
                    price=_price(item.get("price")),
                    calories=_calories(item.get("calories")),
                )
            )
    return clean(dishes)


_PRICE = re.compile(r"\$\s?\d{1,4}(?:\.\d{1,2})?")
_TRAILING_PRICE = re.compile(r"\s*\$\s?\d{1,4}(?:\.\d{1,2})?\s*$")
# "432 cal", "(432 kcal)", "432 calories"; "432 call" is a common misread.
_CALORIES = re.compile(
    r"\s*\(?\b(\d{2,4})\s*(?:kcal|calories|cals?|call)\b\)?", re.IGNORECASE
)


def _price(value):
    """A printed price as "$12.95", or ""."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"${value:.2f}" if value > 0 else ""
    match = _PRICE.search(str(value or ""))
    return match.group(0).replace(" ", "") if match else ""


def _calories(value):
    """Calories as a whole number (10-5000), or None."""
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        return None
    return number if 10 <= number <= 5000 else None


def read_dishes(images):
    """Dishes Gemini reads from *images*; [] (and a 10-minute pause) on quota."""
    if not images or cache.get(GEMINI_PAUSE_KEY):
        return []
    try:
        return _dishes_from(read_menu(images))
    except GeminiQuota:
        logger.warning("Gemini quota reached; pausing menu reading.")
        cache.set(GEMINI_PAUSE_KEY, True, GEMINI_PAUSE_SECONDS)
        return []


def _can_read():
    return bool(settings.GOOGLE_AUTO_FETCH and settings.GEMINI_API_KEY)


MENU_FIELDS = ("name", "description", "kind", "price", "calories")


def _menu_cache_key(place, query):
    place_id = getattr(place, "place_id", "") or ""
    key = place_id or " ".join((query or "").casefold().split())
    return "menu-photos:" + hashlib.sha256(key.encode()).hexdigest()


def photo_dishes(place, query):
    """Dishes read from the restaurant's Google photos, or [].

    A menu that was read is cached for PLACES_CACHE_SECONDS; an empty read
    (no menu photo, quota, errors) is not, so it is tried again next time.
    Fresh Dish objects are made from the cache each time, so one viewer's
    picks never show up for another."""
    seconds = getattr(settings, "PLACES_CACHE_SECONDS", 0)
    key = _menu_cache_key(place, query)
    if seconds:
        hit = cache.get(key)
        if hit:
            return [Dish(**dict(zip(MENU_FIELDS, row))) for row in hit]
    if not (_can_read() and _google_key()) or cache.get(GEMINI_PAUSE_KEY):
        return []
    dishes = read_dishes(download_photos(photo_names(place, query)))
    if dishes and seconds:
        rows = [tuple(getattr(d, f) for f in MENU_FIELDS) for d in dishes]
        cache.set(key, rows, seconds)
    return dishes


_LETTERS = re.compile(r"[A-Za-z]")


def clean(dishes):
    """Drop blank, very short, all-caps-header-like and repeated names; move a
    price or calories written into the name or description to their fields."""
    seen, result = set(), []
    for dish in dishes:
        name = " ".join(dish.name.split())
        dish = _split_extras(
            Dish(**{**dish.__dict__, "name": name, "goals": {}, "notes": []})
        )
        if len(dish.name) < 3 or not _LETTERS.search(dish.name):
            continue
        key = dish.name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(dish)
    return result[:MAX_DISHES]


def _balanced(text):
    """*text* without empty "()" and without ")" that close nothing (left
    behind when "(432 cal" was cut out of "(432 cal, add croutons (+3))")."""
    text = text.replace("()", "")
    kept, depth = [], 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                continue
            depth -= 1
        kept.append(char)
    return "".join(kept)


def _split_extras(dish):
    """Move a price left in the name, or calories left in the description
    (like "(432 cal)"), into their own fields."""
    description = " ".join(dish.description.split())
    if not dish.price:
        match = _TRAILING_PRICE.search(dish.name)
        if match and match.start() >= 3:
            dish.price = _price(match.group(0))
            dish.name = dish.name[: match.start()].strip()
    match = _CALORIES.search(description)
    if match:
        if dish.calories is None:
            dish.calories = _calories(match.group(1))
        start, end = match.span()
        description = _balanced(description[:start] + description[end:])
        description = " ".join(description.split()).strip(" ,;")
    dish.description = description
    return dish


def group(dishes):
    """Dishes grouped as Food, Drinks, Desserts (empty groups left out)."""
    groups = []
    for kind, label in KINDS:
        members = [d for d in dishes if d.kind == kind]
        if members:
            groups.append(Group(label, members))
    return groups


# ---------------------------------------------------------------------------
# Scoring and picking


def score_dishes(dishes, encoder, goals):
    """Fill dish.health and dish.goals (0-1, None when not about food health)."""
    if not dishes:
        return
    sets = [(health_ai.HEALTHY_ANCHORS, health_ai.UNHEALTHY_ANCHORS)]
    sets += [health_ai.GOAL_ANCHORS[goal] for goal in goals]
    anchors = [a for good, bad in sets for a in list(good) + list(bad)]
    vectors = health_ai._unit_rows(encoder(anchors + [d.text for d in dishes]))
    split = len(anchors)
    anchor_vecs, dish_vecs = vectors[:split], vectors[split:]
    start = 0
    for index, (good, bad) in enumerate(sets):
        end = start + len(good) + len(bad)
        sims = dish_vecs @ anchor_vecs[start:end].T
        scores = health_ai._sigmoid_scores(sims, len(good))
        for dish, score in zip(dishes, scores):
            if index == 0:
                dish.health = score
            elif score is not None:
                dish.goals[goals[index - 1]] = score
        start = end


def _profile_lists(profile):
    if profile is None:
        return [], [], [], []
    goals = [
        g for g in normalize_goals(profile.health_goals) if g in health_ai.GOAL_ANCHORS
    ]
    likes = parse_foods(profile.favorite_foods)[0]
    dislikes = parse_foods(profile.disliked_foods)[0]
    allergies = parse_allergies(profile.allergies)
    return goals, likes, dislikes, allergies


def _mentions(option, text):
    words = option.words or (option.label,)
    return bool(name_pattern(words).search(text))


def pick_count(food_count):
    """How many picks a menu with *food_count* dishes gets: none for 3 or
    fewer (picking most of a short menu says little), 2 for 4-5, else PICKS."""
    if food_count <= 3:
        return 0
    if food_count <= 5:
        return 2
    return PICKS


def _calorie_scores(dishes):
    """{dish index: 0-1} (1 = fewest calories on this menu), only when every
    dish lists calories, so dishes are compared on the same footing."""
    calories = [d.calories for d in dishes]
    if not calories or any(c is None for c in calories):
        return {}
    low, high = min(calories), max(calories)
    if high == low:
        return {}
    return {i: (high - c) / (high - low) for i, c in enumerate(calories)}


def pick(dishes, profile, count=PICKS, skipped=None):
    """Top healthy dishes for this user, with short notes on why.

    Only dishes with health >= HEALTHY_AT are picked. A dish listing one of
    the user's allergens is left out (added to *skipped* as (name, words));
    a disliked dish is ranked down, not removed."""
    goals, likes, dislikes, allergies = _profile_lists(profile)
    calorie_scores = _calorie_scores(dishes)
    lightest = max(calorie_scores.values()) if calorie_scores else None
    choices = []
    for index, dish in enumerate(dishes):
        if dish.health is None or dish.health < HEALTHY_AT:
            continue
        words = allergen_words_in(allergies, dish.text)
        if words:
            if skipped is not None:
                skipped.append((dish.name, words))
            continue
        goal_scores = [dish.goals.get(goal, 0.5) for goal in goals]
        rank = dish.health
        if goal_scores:
            rank = 0.6 * dish.health + 0.4 * sum(goal_scores) / len(goal_scores)
        if "weight-loss" in goals and calorie_scores:
            rank += CALORIE_WEIGHT * calorie_scores[index]
        liked = next((o for o in likes if _mentions(o, dish.text)), None)
        if liked:
            rank += LIKE_BONUS
        if any(_mentions(option, dish.text) for option in dislikes):
            rank -= DISLIKE_PENALTY
        fitting = [g for g in goals if dish.goals.get(g, 0) >= GOAL_FITS_AT]
        notes = []
        if fitting:
            best = max(fitting, key=lambda g: dish.goals[g])
            notes.append(f"Fits {GOAL_LABELS[best].lower()}")
        if liked:
            notes.append(f"You like {liked.label.lower()}")
        if not notes:
            notes.append("Lighter choice")
        if calorie_scores and calorie_scores[index] == lightest:
            notes.append("Lightest here")
        dish.rank, dish.notes = rank, notes
        choices.append(dish)
    choices.sort(key=lambda d: -d.rank)
    return choices[:count]


def build(name, place, profile, query, get_encoder=None):
    """The menu for one restaurant, grouped by kind, with food picks for
    this user highlighted (never raises).

    ``get_encoder`` returns the MiniLM encoder (or None); without it the
    menu is shown with no picks.
    """
    try:
        source, dishes = "menustat", menustat_dishes(name)
        if not dishes:
            source, dishes = "photos", photo_dishes(place, query)
    except Exception:
        logger.warning("Menu lookup failed for %s", name, exc_info=True)
        return Result(message="Menu not available right now.")
    if not dishes:
        return Result(message="Menu not available.")
    result = Result(source=source, groups=group(dishes))
    try:
        _add_picks(result, dishes, profile, get_encoder)
    except Exception:
        logger.warning("Menu picks failed for %s", name, exc_info=True)
        for dish in dishes:
            dish.picked = False
        result.picks, result.skipped = [], []
    return result


def _add_picks(result, dishes, profile, get_encoder):
    goals = _profile_lists(profile)[0]
    result.goal_labels = [GOAL_LABELS[goal] for goal in goals]
    food = [dish for dish in dishes if dish.kind == "food"]
    count = pick_count(len(food))
    encoder = get_encoder() if (count and get_encoder) else None
    if encoder is None:
        return
    score_dishes(food, encoder, goals)
    skipped = []
    result.picks = pick(food, profile, count, skipped)
    result.skipped = skipped[:3]
    for dish in result.picks:
        dish.picked = True
