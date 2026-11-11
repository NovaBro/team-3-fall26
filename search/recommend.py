"""Rule-based Top Picks recommendation score (v3).

score_restaurant() returns (score 0–100+, reason tags, breakdown). Pure logic — no I/O.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Iterable

DEFAULT_WEIGHTS = (0.50, 0.25, 0.25)  # health, grade, rating
HEALTH_FOCUS_WEIGHTS = (0.60, 0.25, 0.15)
# When MenuStat calories are available: other weights × 0.9, calorie = 0.10
CALORIE_WEIGHT = 0.10
RATING_PRIOR = 4.0
RATING_PSEUDO_COUNT = 20
LOWER_CALORIE_TAG_THRESHOLD = 0.6  # calorie component ≥ this → tag

# Like / Not interested feedback (see FeedbackPrefs and feedback_adjustment).
LIKE_BONUS_PER_PLACE = 3.0
LIKE_BONUS_CAP = 9.0
NOT_INTERESTED_CUISINE_MIN = 2  # marks of one cuisine before it is penalized
NOT_INTERESTED_CUISINE_PENALTY = -5.0
LIKED_STARS = 4  # star ratings at or above this count as a like
DISLIKED_STARS = 2  # star ratings at or below this count as not interested
BECAUSE_YOU_LIKED = "Because you liked {name}"
TAG_YOU_LIKED = "You liked this"

HEALTHY_CUISINES = {
    "Salads",
    "Vegetarian",
    "Vegan",
    "Juice, Smoothies, Fruit Salads",  # exact DOHMH label
    "Soups/Salads/Sandwiches",
    "Fruits/Vegetables",
    "Soups",
    "Mediterranean",
    "Greek",
    "Middle Eastern",
    "Japanese",
    "Korean",
    "Seafood",
    "Hawaiian",
}

UNHEALTHY_CUISINES = {
    "Hamburgers",
    "Hotdogs",
    "Chicken",
    "Pizza",
    "Donuts",
    "Frozen Desserts",
    "Bakery Products/Desserts",
    "Nuts/Confectionary",
}

HEALTHY_WORDS = {
    "healthy",
    "fresh",
    "salad",
    "grilled",
    "steamed",
    "organic",
    "light",
    "vegan",
    "vegetarian",
    "nutritious",
    "lean",
    "greens",
    "smoothie",
    "balanced",
}

UNHEALTHY_WORDS = {
    "greasy",
    "oily",
    "fried",
    "heavy",
    "salty",
    "sugary",
    "processed",
    "fatty",
    "unhealthy",
    "junk",
}

# muscle-gain adds protein/chicken per PDF; other goals add mild cues.
GOAL_HEALTHY_WORDS = {
    "muscle-gain": {"protein", "chicken", "protein-rich"},
    "heart-health": {"heart", "lean", "omega"},
    "more-energy": {"energizing", "fuel"},
    "balanced-diet": {"balanced", "wholesome"},
    "manage-condition": {"gentle", "plain"},
    "weight-loss": {"light", "low-calorie", "lean"},
}

# 23 brands (aliases allowed). Subway, Chipotle, Sweetgreen intentionally omitted.
FAST_FOOD_PREFIXES = (
    "mcdonald's",
    "mcdonalds",
    "burger king",
    "wendy's",
    "wendys",
    "taco bell",
    "popeyes",
    "kfc",
    "domino's",
    "dominos",
    "papa john's",
    "papa johns",
    "pizza hut",
    "wingstop",
    "five guys",
    "chick-fil-a",
    "chickfila",
    "chick fil a",
    "dunkin'",
    "dunkin",
    "arby's",
    "arbys",
    "sonic",
    "carl's jr",
    "carls jr",
    "jack in the box",
    "little caesars",
    "little caesar's",
    "whataburger",
    "culver's",
    "culvers",
    "hardee's",
    "hardees",
)

# Top picks recommend places for a meal. These cuisines are drinks, desserts
# or snacks, so they are left out of Top picks (Explore more still lists them,
# lower down). Juice / smoothie bars stay: they fit a healthy-food app.
NON_MEAL_CUISINES = {
    "Coffee/Tea",
    "Bakery Products/Desserts",
    "Donuts",
    "Frozen Desserts",
    "Bagels/Pretzels",
    "Bottled Beverages",
    "Nuts/Confectionary",
}

# Coffee / dessert chains whose inspection rows are sometimes filed under
# another cuisine (e.g. some Starbucks are "American" or blank).
NON_MEAL_PREFIXES = (
    "starbucks",
    "tim hortons",
    "blue bottle",
    "gregorys coffee",
    "gregory's coffee",
    "bluestone lane",
    "joe coffee",
    "birch coffee",
    "think coffee",
    "la colombe",
    "cafe grumpy",
    "peet's coffee",
    "peets coffee",
    "coffee bean",
    "krispy kreme",
    "insomnia cookies",
    "baskin robbins",
    "baskin-robbins",
    "carvel",
    "16 handles",
    "pinkberry",
    "yogurtland",
)

BOROUGHS = (
    "Manhattan",
    "Brooklyn",
    "Queens",
    "Bronx",
    "Staten Island",
)

TAG_YOUR_FAVORITE = "Your favorite"
TAG_NEARBY = "Nearby"
TAG_HEALTHY_REVIEWS = "Healthy reviews"
TAG_LOWER_CALORIE = "Lower-calorie menu"
TAG_BUDGET = "Budget-friendly"
TAG_TOP_RATED = "Top rated"
TAG_GRADE_A = "Grade A"

TAG_ORDER = (
    TAG_YOUR_FAVORITE,
    TAG_NEARBY,
    TAG_HEALTHY_REVIEWS,
    TAG_LOWER_CALORIE,
    TAG_BUDGET,
    TAG_TOP_RATED,
    TAG_GRADE_A,
)

_WORD_RE = re.compile(r"[a-z0-9']+")
_ZIP_RE = re.compile(r"\b(\d{5})\b")


def bmi(weight_lbs, height_in):
    """Imperial BMI, or None if inputs are missing/invalid."""
    try:
        w = float(weight_lbs)
        h = float(height_in)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return 703.0 * w / (h * h)


def health_focus_weights(profile=None):
    """True when BMI ≥ 25 or the profile has a weight-loss goal."""
    if profile is None:
        return False
    goals = getattr(profile, "health_goals", None) or []
    if "weight-loss" in goals:
        return True
    value = bmi(
        getattr(profile, "weight_lbs", None),
        getattr(profile, "height_in", None),
    )
    return value is not None and value >= 25.0


def _base_weights(profile=None):
    if health_focus_weights(profile):
        return HEALTH_FOCUS_WEIGHTS
    return DEFAULT_WEIGHTS


def _weights(profile=None, has_calories=False):
    """Return (health, grade, rating) or (health, grade, rating, calorie)."""
    base = _base_weights(profile)
    if not has_calories:
        return base
    scale = 1.0 - CALORIE_WEIGHT
    return tuple(w * scale for w in base) + (CALORIE_WEIGHT,)


def _tokenize(text):
    return _WORD_RE.findall((text or "").casefold())


def whole_word_match(needle, *haystacks):
    """True if needle appears as a whole word in any haystack."""
    needle = (needle or "").strip()
    if not needle:
        return False
    pattern = re.compile(rf"\b{re.escape(needle)}\b", re.IGNORECASE)
    return any(pattern.search(h or "") for h in haystacks)


def split_foods(text):
    """Comma/semicolon/newline separated favorite or disliked foods."""
    if not text:
        return []
    return [part.strip() for part in re.split(r"[,;\n]+", text) if part.strip()]


def allergy_keys_from_text(allergies):
    """Map free-text allergies to diet_filters keys (nuts, shellfish)."""
    text = (allergies or "").casefold()
    keys = []
    if re.search(r"\b(peanuts?|tree\s*nuts?|nuts?)\b", text):
        keys.append("nuts")
    if re.search(r"\b(shellfish|shrimp|lobster|crab|mussels?|clams?)\b", text):
        keys.append("shellfish")
    return keys


def home_zip_boro(home_address):
    """Parse first 5-digit ZIP and a borough keyword from free-text address."""
    text = home_address or ""
    zip_match = _ZIP_RE.search(text)
    zipcode = zip_match.group(1) if zip_match else ""
    boro = ""
    lower = text.casefold()
    # Longer names first so "Staten Island" wins over partials.
    for name in sorted(BOROUGHS, key=len, reverse=True):
        if name.casefold() in lower:
            boro = name
            break
    return zipcode, boro


def is_fast_food(name):
    """True if the restaurant name starts with a known fast-food brand."""
    normalized = " ".join((name or "").casefold().split())
    if not normalized:
        return False
    # Also check segments after " / " so "KFC/TACO BELL" matches.
    segments = [normalized] + [
        part.strip() for part in re.split(r"[/|]", normalized) if part.strip()
    ]
    for segment in segments:
        for prefix in FAST_FOOD_PREFIXES:
            if segment == prefix or segment.startswith(prefix + " "):
                return True
            # Allow glued forms like "chick-fil-a #123"
            if segment.startswith(prefix):
                rest = segment.removeprefix(prefix)
                if not rest or rest[0] in " #-(":
                    return True
    return False


def _goal_words(profile):
    words = set()
    if profile is None:
        return words
    for goal in getattr(profile, "health_goals", None) or []:
        words.update(GOAL_HEALTHY_WORDS.get(goal, set()))
    return words


def _review_texts(reviews):
    texts = []
    for item in reviews or []:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, dict):
            texts.append(item.get("text") or "")
        else:
            texts.append(str(item))
    return texts


def classify_reviews(reviews, extra_healthy: Iterable[str] = ()):
    """Return (healthy_count, unhealthy_count, total) — each review once."""
    healthy_vocab = HEALTHY_WORDS | {w.casefold() for w in extra_healthy}
    unhealthy_vocab = UNHEALTHY_WORDS
    healthy = unhealthy = 0
    texts = _review_texts(reviews)
    for text in texts:
        tokens = set(_tokenize(text))
        h = sum(1 for t in tokens if t in healthy_vocab)
        u = sum(1 for t in tokens if t in unhealthy_vocab)
        if h > u:
            healthy += 1
        elif u > h:
            unhealthy += 1
    return healthy, unhealthy, len(texts)


DISPLAY_REVIEW_MIN_STARS = 4  # Top picks cards only show 4-5 star reviews


def pick_display_review(reviews, profile=None):
    """The review to show on a Top picks card.

    Only 4-5 star reviews are shown (a 1-star quote under a recommendation is
    confusing; the rating score still uses every review). Among those, prefer
    the review the health check counts as healthy (more healthy words than
    unhealthy ones) with the most healthy words; ties keep Google's relevance
    order. With no healthy review, fall back to the first 4-5 star review.
    Returns the original review dict, or None when nothing qualifies.
    """
    reviews = [
        r
        for r in reviews or []
        if (_review_texts([r])[0] or "").strip()
        and isinstance(r, dict)
        and (r.get("rating") or 0) >= DISPLAY_REVIEW_MIN_STARS
    ]
    if not reviews:
        return None
    healthy_vocab = HEALTHY_WORDS | _goal_words(profile)
    best, best_count = None, 0
    for review in reviews:
        tokens = set(_tokenize(_review_texts([review])[0]))
        good = sum(1 for t in tokens if t in healthy_vocab)
        bad = sum(1 for t in tokens if t in UNHEALTHY_WORDS)
        if good > bad and good > best_count:
            best, best_count = review, good
    return best if best is not None else reviews[0]


def health_score(cuisine, reviews, name, goal_words=()):
    """Health component in [0, 1]."""
    score = 0.5
    cuisine = (cuisine or "").strip()
    if cuisine in HEALTHY_CUISINES:
        score += 0.2
    elif cuisine in UNHEALTHY_CUISINES:
        score -= 0.2

    healthy, unhealthy, total = classify_reviews(reviews, goal_words)
    if total:
        score += 0.3 * ((healthy / total) - (unhealthy / total))

    if is_fast_food(name):
        score -= 0.2

    return max(0.0, min(1.0, score))


def grade_score(grade):
    """Inspection grade component in [0, 1]."""
    g = (grade or "").strip().upper()
    if g == "A":
        return 1.0
    if g == "B":
        return 0.5
    if g == "C":
        return 0.0
    return 0.3


def blended_rating(google_rating, google_count, app_avg, app_count):
    """Bayesian blend toward prior 4.0 with pseudo-count 20."""
    try:
        g_rating = float(google_rating) if google_rating is not None else None
    except (TypeError, ValueError):
        g_rating = None
    try:
        g_count = int(google_count or 0)
    except (TypeError, ValueError):
        g_count = 0
    try:
        a_avg = float(app_avg) if app_avg is not None else None
    except (TypeError, ValueError):
        a_avg = None
    try:
        a_count = int(app_count or 0)
    except (TypeError, ValueError):
        a_count = 0

    g_count = max(0, g_count)
    a_count = max(0, a_count)
    numerator = RATING_PRIOR * RATING_PSEUDO_COUNT
    denominator = RATING_PSEUDO_COUNT
    if g_rating is not None and g_count > 0:
        numerator += g_rating * g_count
        denominator += g_count
    if a_avg is not None and a_count > 0:
        numerator += a_avg * a_count
        denominator += a_count
    return numerator / denominator, g_count + a_count


def rating_score(google_rating, google_count, app_avg, app_count):
    """Rating component in [0, 1] from blended stars (3.0→0, 5.0→1)."""
    blended, _votes = blended_rating(google_rating, google_count, app_avg, app_count)
    return max(0.0, min(1.0, (blended - 3.0) / 2.0))


def score_restaurant(
    *,
    name,
    cuisine="",
    grade="",
    google_rating=None,
    google_count=0,
    app_avg=None,
    app_count=0,
    reviews=None,
    price=None,
    zipcode="",
    boro="",
    profile=None,
    calorie_score=None,
    feedback=None,
    camis="",
):
    """Return (final_score, reason_tags, breakdown) for one restaurant.

    ``calorie_score`` is a 0–1 MenuStat median-meal component when linked; omit
    (None) to keep the three-part weights. ``feedback`` is the viewer's
    FeedbackPrefs (Like / Not interested history); None leaves the score as is.
    ``camis`` keeps a place's own Like from boosting itself.
    """
    goal_words = _goal_words(profile)
    h = health_score(cuisine, reviews, name, goal_words)
    g = grade_score(grade)
    r = rating_score(google_rating, google_count, app_avg, app_count)
    has_calories = calorie_score is not None
    focus = health_focus_weights(profile)
    weights = _weights(profile, has_calories=has_calories)
    if has_calories:
        w_h, w_g, w_r, w_c = weights
        c = max(0.0, min(1.0, float(calorie_score)))
        base_points = 100.0 * (h * w_h + g * w_g + r * w_r + c * w_c)
    else:
        w_h, w_g, w_r = weights
        c = None
        w_c = None
        base_points = 100.0 * (h * w_h + g * w_g + r * w_r)

    score = base_points
    adjustments = []
    is_favorite = False
    is_nearby = False
    if profile is not None:
        for food in split_foods(getattr(profile, "favorite_foods", "")):
            if whole_word_match(food, cuisine, name):
                score += 10.0
                is_favorite = True
                adjustments.append({"label": "Favorite food match", "delta": 10.0})
                break
        for food in split_foods(getattr(profile, "disliked_foods", "")):
            if whole_word_match(food, cuisine, name):
                score -= 15.0
                adjustments.append({"label": "Disliked food match", "delta": -15.0})
                break
        home_zip, home_boro = home_zip_boro(getattr(profile, "home_address", ""))
        if (home_zip and home_zip == (zipcode or "").strip()) or (
            home_boro and home_boro.casefold() == (boro or "").strip().casefold()
        ):
            score += 5.0
            is_nearby = True
            adjustments.append({"label": "Near home", "delta": 5.0})

    like_bonus, liked_tag = 0.0, None
    if feedback is not None:
        like_bonus, cuisine_penalty, liked_tag = feedback_adjustment(
            cuisine, feedback, camis
        )
        if like_bonus:
            score += like_bonus
            adjustments.append(
                {"label": "Similar to places you liked", "delta": like_bonus}
            )
        if cuisine_penalty:
            score += cuisine_penalty
            adjustments.append(
                {"label": "Cuisine you marked not interested", "delta": cuisine_penalty}
            )

    healthy_n, _unhealthy_n, total = classify_reviews(reviews, goal_words)
    blended, vote_count = blended_rating(
        google_rating, google_count, app_avg, app_count
    )

    candidates = []
    if is_favorite:
        candidates.append(TAG_YOUR_FAVORITE)
    if is_nearby:
        candidates.append(TAG_NEARBY)
    if total and healthy_n >= 2 and (healthy_n / total) >= 0.40:
        candidates.append(TAG_HEALTHY_REVIEWS)
    if c is not None and c >= LOWER_CALORIE_TAG_THRESHOLD:
        candidates.append(TAG_LOWER_CALORIE)
    if price == "$":
        candidates.append(TAG_BUDGET)
    if vote_count >= 50 and blended >= 4.5:
        candidates.append(TAG_TOP_RATED)
    if (grade or "").strip().upper() == "A":
        candidates.append(TAG_GRADE_A)

    tags = [tag for tag in TAG_ORDER if tag in candidates]
    if liked_tag:
        tags.insert(0, liked_tag)
    # The card shows the grade only here (no photo badge), so B and C appear too.
    if (grade or "").strip().upper() in ("B", "C"):
        tags.append(f"Grade {(grade or '').strip().upper()}")

    def _part(key, label, value, weight):
        return {
            "key": key,
            "label": label,
            "value_0_1": value,
            "weight": weight,
            "weight_pct": weight * 100.0,
            "points": 100.0 * value * weight,
        }

    parts = [
        _part("health", "Health", h, w_h),
        _part("grade", "Inspection grade", g, w_g),
        _part("rating", "Rating", r, w_r),
    ]
    if has_calories:
        parts.append(_part("calories", "Menu calories", c, w_c))

    breakdown = {
        "mode": "health_focus" if focus else "default",
        "has_calories": has_calories,
        "parts": parts,
        "adjustments": adjustments,
        "base_points": base_points,
        "total": score,
        "tags": tags,
        "like_bonus": like_bonus,
    }
    return score, tags, breakdown


# ---------------------------------------------------------------------------
# Daily rotation, cuisine diversity, and Like / Not interested feedback.


@dataclass
class FeedbackPrefs:
    """What one user told us: liked places by cuisine, hidden places, and how
    many places of each cuisine they marked not interested."""

    liked: dict = field(default_factory=dict)  # cuisine -> [(camis, name)]
    hidden: set = field(default_factory=set)  # camis never to show again
    not_interested: dict = field(default_factory=dict)  # cuisine -> count

    def is_empty(self):
        return not (self.liked or self.hidden or self.not_interested)


def build_feedback_prefs(explicit=(), star_ratings=()):
    """Combine button feedback and star ratings into FeedbackPrefs.

    ``explicit``: (camis, name, cuisine, value) with value +1 like / -1 not
    interested. ``star_ratings``: (camis, name, cuisine, stars 1-5); 4-5 counts
    as a like and 1-2 as not interested. A button press wins over a star rating
    for the same restaurant.
    """
    by_camis = {}
    for camis, name, cuisine, stars in star_ratings:
        if stars >= LIKED_STARS:
            by_camis[camis] = (name, cuisine, 1)
        elif stars <= DISLIKED_STARS:
            by_camis[camis] = (name, cuisine, -1)
    for camis, name, cuisine, value in explicit:
        by_camis[camis] = (name, cuisine, 1 if value > 0 else -1)

    prefs = FeedbackPrefs()
    for camis, (name, cuisine, value) in by_camis.items():
        cuisine = (cuisine or "").strip()
        if value > 0:
            if cuisine:
                prefs.liked.setdefault(cuisine, []).append((camis, name or ""))
        else:
            prefs.hidden.add(camis)
            if cuisine:
                prefs.not_interested[cuisine] = prefs.not_interested.get(cuisine, 0) + 1
    return prefs


def feedback_adjustment(cuisine, prefs, camis=""):
    """(like bonus, cuisine penalty, reason tag or None) for one place.

    The bonus counts *other* liked places with the same cuisine; a place the
    user liked itself gets the "You liked this" tag instead of a bonus.
    """
    cuisine = (cuisine or "").strip()
    if not cuisine or prefs is None:
        return 0.0, 0.0, None
    liked = prefs.liked.get(cuisine, [])
    others = [name for liked_camis, name in liked if liked_camis != camis]
    bonus = min(LIKE_BONUS_CAP, LIKE_BONUS_PER_PLACE * len(others))
    penalty = 0.0
    if prefs.not_interested.get(cuisine, 0) >= NOT_INTERESTED_CUISINE_MIN:
        penalty = NOT_INTERESTED_CUISINE_PENALTY
    tag = None
    if camis and len(others) < len(liked):
        tag = TAG_YOU_LIKED
    elif bonus and others[0]:
        tag = BECAUSE_YOU_LIKED.format(name=others[0].title())
    return bonus, penalty, tag


def daily_seed(day, user_id=None):
    """Seed string: same day + same user -> same picks; next day -> new picks."""
    return f"{day.isoformat()}:{user_id or 0}"


def daily_sample(rows, size, seed):
    """Deterministic sample of *size* rows for this seed (order kept)."""
    rows = list(rows)
    if len(rows) <= size:
        return rows
    chosen = set(random.Random(seed).sample(range(len(rows)), size))
    return [row for index, row in enumerate(rows) if index in chosen]


def pick_top(items, count=3):
    """Pick the final *count* items from scored dicts.

    Each item needs ``score``, ``cuisine`` and ``like_bonus``. Rules:
    1. Highest score first, but skip a cuisine that is already chosen; refill
       from the skipped items if fewer than *count* remain.
    2. At most one pick may use its like bonus. Other liked items compete with
       their score minus the bonus.
    """
    pool = sorted(items, key=lambda item: -item["score"])
    chosen, skipped, cuisines = [], [], set()
    bonus_used = False
    while pool and len(chosen) < count:
        item = pool.pop(0)
        if item.get("like_bonus") and bonus_used:
            item = dict(item, score=item["score"] - item["like_bonus"], like_bonus=0)
            pool.append(item)
            pool.sort(key=lambda other: -other["score"])
            continue
        cuisine = (item.get("cuisine") or "").strip()
        if cuisine and cuisine in cuisines:
            skipped.append(item)
            continue
        chosen.append(item)
        if cuisine:
            cuisines.add(cuisine)
        bonus_used = bonus_used or bool(item.get("like_bonus"))
    for item in skipped:
        if len(chosen) >= count:
            break
        chosen.append(item)
    return chosen
