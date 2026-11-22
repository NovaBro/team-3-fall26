"""Gemini-estimated menus for restaurants without a MenuStat menu.

Run ``python manage.py estimate_menus`` on a developer machine: Gemini gets
only our own data (restaurant name, cuisine, borough, street) and guesses a
typical menu with rough calories per dish. The answer is stored in
``community.MenuEstimate``; the web server only reads it.

These are estimates, not the real menu:

- The Menu box shows them last (after MenuStat and Google-photo reading),
  labeled "Estimated by AI".
- Ranking blends their median main-dish calories 50/50 with the soft health
  prior, keeps the no-menu weights, and keeps confidence low
  (see ``recommend.score_restaurant``).
"""

from __future__ import annotations

import json
import re
import statistics
import time

import requests
from django.conf import settings

from search.menustat import MIN_MEALS_FOR_SCORE, calorie_score_from_median

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_TIMEOUT = 90
PROMPT_VERSION = "v1"  # bump when the prompt changes; older estimates are redone
KINDS = ("main", "side", "drink", "dessert")
MAX_ITEMS = 30
MAX_KCAL = 3000
RETRY_STATUSES = (500, 502, 503, 504)  # Gemini "overloaded" errors: try again
RETRY_WAITS = (5, 15, 30)  # seconds before each retry

PROMPT = (
    "You estimate restaurant menus for a NYC food-search app. For each "
    "restaurant below (from Google Maps), list 12 to 20 "
    "items it most likely serves, based on its name, cuisine and borough. "
    "These are labeled as estimates, so give typical dishes for this kind of "
    "place; if the name suggests specialties, include them. For each item "
    'give "name", a short "description" (under 12 words), "kind" (one of '
    '"main", "side", "drink", "dessert") and "calories": a rough estimate '
    "for one typical NYC serving, as a whole number. Include at least 6 "
    "mains. Reply ONLY with JSON: "
    '{"restaurants": [{"id": "...", "items": [{"name": "...", '
    '"description": "...", "kind": "main", "calories": 650}]}]} '
    "with one entry per restaurant, using the given id.\n\nRestaurants:\n"
)


class RateLimited(Exception):
    """Gemini quota or rate limit reached."""


def model_tag(model_name):
    """What we store in MenuEstimate.model_name: model plus prompt version."""
    return f"{model_name}|{PROMPT_VERSION}"


def is_current(stored_tag):
    """True if an estimate was made with the current prompt."""
    return (stored_tag or "").endswith(f"|{PROMPT_VERSION}")


def build_prompt(restaurants):
    """Prompt for a batch of {"id", "name", "cuisine", "boro", "street"} dicts."""
    lines = [
        json.dumps(
            {
                "id": r["id"],
                "name": r.get("name") or "",
                "cuisine": r.get("cuisine") or "",
                "borough": r.get("boro") or "",
                "street": r.get("street") or "",
            }
        )
        for r in restaurants
    ]
    return PROMPT + "\n".join(lines)


def gemini_generate(model_name=None, api_key=None, sleep=time.sleep):
    """Return ``generate(prompt) -> text`` backed by the Gemini REST API.

    Busy-server errors (5xx) are retried after ``RETRY_WAITS`` seconds.
    """
    model_name = model_name or settings.GEMINI_MODEL
    api_key = api_key or settings.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY in .env (from aistudio.google.com).")

    def generate(prompt):
        for wait in (*RETRY_WAITS, None):
            resp = requests.post(
                f"{GEMINI_URL}/{model_name}:generateContent",
                headers={"x-goog-api-key": api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=GEMINI_TIMEOUT,
            )
            if resp.status_code not in RETRY_STATUSES or wait is None:
                break
            sleep(wait)
        if resp.status_code in (402, 429):
            raise RateLimited(resp.text[:200])
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    return generate


def parse_answer(text):
    """{id: [raw item dicts]} from Gemini's JSON answer ({} if unusable)."""
    try:
        answer = json.loads(text or "")
    except (TypeError, ValueError):
        return {}
    entries = answer.get("restaurants") if isinstance(answer, dict) else answer
    result = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        items = entry.get("items")
        if entry.get("id") is not None and isinstance(items, list):
            result[str(entry["id"])] = [i for i in items if isinstance(i, dict)]
    return result


_LETTERS = re.compile(r"[A-Za-z]")


def _calories(value):
    try:
        kcal = float(value)
    except (TypeError, ValueError):
        return None
    if kcal <= 0:
        return None
    return round(min(kcal, MAX_KCAL))


def clean_items(items):
    """Keep well-formed items: known kind, readable unique name, sane kcal."""
    seen, result = set(), []
    for item in items:
        name = " ".join(str(item.get("name") or "").split())
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in KINDS or len(name) < 3 or not _LETTERS.search(name):
            continue
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        result.append(
            {
                "name": name,
                "description": " ".join(str(item.get("description") or "").split()),
                "kind": kind,
                "calories": _calories(item.get("calories")),
            }
        )
    return result[:MAX_ITEMS]


def summarize(items):
    """(median kcal of mains, number of mains with kcal); median None if < 3."""
    mains = [i["calories"] for i in items if i["kind"] == "main" and i["calories"]]
    if len(mains) < MIN_MEALS_FOR_SCORE:
        return None, len(mains)
    return float(statistics.median(mains)), len(mains)


def estimate_batch(restaurants, generate):
    """{id: cleaned items} for a batch; restaurants Gemini skipped are left out."""
    answer = parse_answer(generate(build_prompt(restaurants)))
    wanted = {str(r["id"]) for r in restaurants}
    result = {}
    for rid, items in answer.items():
        cleaned = clean_items(items)
        if rid in wanted and cleaned:
            result[rid] = cleaned
    return result


def _row(place_id):
    from community.models import MenuEstimate

    if not place_id:
        return None
    row = MenuEstimate.objects.filter(place_id=place_id).first()
    if row is None or not is_current(row.model_name):
        return None
    return row


def estimate_nutrition_for_place(place_id):
    """{score, median_calories, meal_count} from a stored estimate, or None."""
    row = _row(place_id)
    if row is None or row.median_calories is None:
        return None
    score = calorie_score_from_median(row.median_calories)
    if score is None:
        return None
    return {
        "score": score,
        "median_calories": row.median_calories,
        "meal_count": row.meal_count,
    }


def estimated_items(place_id):
    """Stored estimated items for a restaurant ([] when none)."""
    row = _row(place_id)
    return list(row.items) if row is not None else []
