"""What to order: the restaurant's menu, and (later) dish picks from it.

Where the menu comes from:

1. MenuStat (chains in our DB): read from our own table, no API cost.
2. Otherwise the restaurant's Google photos: up to 10 photos are downloaded
   and one Gemini call finds the menu photos and reads the dish names.
Nothing from step 2 is saved. Google's terms don't allow storing Places
content (only place IDs), so the menu is read again on each visit.

For now the page shows the whole menu, grouped into food, drinks and
desserts. ``score_dishes`` and ``pick`` (MiniLM health score per dish, the
user's goals, dislikes and allergies) are kept for the next step but not
shown yet.
"""

from __future__ import annotations

import base64
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
    allergens_in,
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

READ_PROMPT = (
    "These are photos of one restaurant. Find the photos that show a menu "
    "(printed menu, menu board or menu page; not just a plate of food) and "
    "list every item you can read on them. Skip words cut off at the photo "
    "edge. For each item give its name exactly as written, its description "
    'if one is printed, and a kind: "food", "drink", "dessert" or "header" '
    "(section titles like APPETIZERS). Reply ONLY with JSON: "
    '{"items": [{"name": "...", "description": "...", "kind": "food"}]}. '
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
    health: float | None = None
    goals: dict = field(default_factory=dict)
    rank: float = 0.0
    notes: list = field(default_factory=list)

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
        .values_list("item_name", "item_description", "food_category")
    )
    dishes = []
    for item, desc, category in rows:
        kind = MENUSTAT_KINDS.get(category, "food")
        if kind:
            dishes.append(Dish(item or "", desc or "", kind))
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
            "generationConfig": {"responseMimeType": "application/json"},
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
            name = str(item.get("name") or "")
            dishes.append(Dish(name, str(item.get("description") or ""), kind))
    return clean(dishes)


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


def photo_dishes(place, query):
    """Dishes read from the restaurant's Google photos, or []."""
    if not (_can_read() and _google_key()) or cache.get(GEMINI_PAUSE_KEY):
        return []
    return read_dishes(download_photos(photo_names(place, query)))


_LETTERS = re.compile(r"[A-Za-z]")


def clean(dishes):
    """Drop blank, very short, all-caps-header-like and repeated names."""
    seen, result = set(), []
    for dish in dishes:
        name = " ".join(dish.name.split())
        if len(name) < 3 or not _LETTERS.search(name):
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(Dish(name, " ".join(dish.description.split()), dish.kind))
    return result[:MAX_DISHES]


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


def pick(dishes, profile):
    """Top dishes for this user, with short notes on why."""
    goals, likes, dislikes, allergies = _profile_lists(profile)
    choices = []
    for dish in dishes:
        if dish.health is None:
            continue
        if allergens_in(allergies, dish.text):
            continue
        if any(_mentions(option, dish.text) for option in dislikes):
            continue
        goal_scores = [dish.goals.get(goal, 0.5) for goal in goals]
        rank = dish.health
        if goal_scores:
            rank = 0.6 * dish.health + 0.4 * sum(goal_scores) / len(goal_scores)
        liked = next((o for o in likes if _mentions(o, dish.text)), None)
        if liked:
            rank += LIKE_BONUS
        notes = [
            f"Fits {GOAL_LABELS[goal].lower()}"
            for goal in goals
            if dish.goals.get(goal, 0) >= GOAL_FITS_AT
        ][:1]
        if liked:
            notes.append(f"you like {liked.label.lower()}")
        if not notes and dish.health >= 0.75:
            notes.append("Lighter choice")
        dish.rank, dish.notes = rank, notes
        choices.append(dish)
    choices.sort(key=lambda d: -d.rank)
    return choices[:PICKS]


def build(name, place, profile, query, get_encoder=None):
    """The menu for one restaurant, grouped by kind (never raises).

    ``profile`` and ``get_encoder`` are for the dish picks (next step); the
    menu is shown as read for now.
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
    return Result(source=source, groups=group(dishes))
