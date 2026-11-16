"""Rule-based Top Picks recommendation score (v3).

score_restaurant() returns (score 0–100, reason tags, breakdown). Pure logic — no I/O.

Parts: Health, Inspection grade, Rating, and (for a viewer with a profile or
Like / Not interested history) Personal fit, which holds everything personal:
favorite and disliked foods, health goals, mild allergies, home area and
Like / Not interested feedback.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Iterable

from search.goal_fit import MENU_NUTRIENTS, goal_fit, goals_fit
from search.profile_options import (
    ALLERGY_LABELS,
    first_food_match,
    mild_allergy_hits,
    normalize_goals,
    parse_allergies,
    parse_foods,
)

DEFAULT_WEIGHTS = (0.50, 0.25, 0.25)  # health, grade, rating
PERSONAL_WEIGHTS = (0.40, 0.20, 0.20, 0.20)  # health, grade, rating, personal
# When MenuStat calories are available: other weights × 0.9, calorie = 0.10
CALORIE_WEIGHT = 0.10
RATING_PRIOR = 4.0
RATING_PSEUDO_COUNT = 20
LOWER_CALORIE_TAG_THRESHOLD = 0.6  # calorie component ≥ this → tag

# Personal fit (0-1): starts at 0.5, then each match below moves it.
FIT_START = 0.5
FIT_FAVORITE = 0.3
FIT_DISLIKED = -0.4
# (goal fit - 0.5) x 1.2 -> -0.6 .. +0.6; x1.2 picked by comparing settings on
# real reviews (evaluate_personal_fit.py): a goal changes 2-3 of a Top 10.
FIT_GOAL_RANGE = 1.2
FIT_MILD_ALLERGY = -0.2
FIT_NEAR_HOME = 0.1
# BMI 25+ without Muscle gain (or Weight loss already picked) counts as a
# Weight loss goal at half strength: lighter places move up a little.
BMI_LEAN_MIN = 25.0
BMI_LEAN_SHARE = 0.5

# Like / Not interested feedback (see FeedbackPrefs and feedback_adjustment).
LIKE_BONUS_PER_PLACE = 0.1  # Personal fit per other liked place, same cuisine
LIKE_BONUS_CAP = 0.3
NOT_INTERESTED_CUISINE_MIN = 2  # marks of one cuisine before it is penalized
NOT_INTERESTED_CUISINE_PENALTY = -0.2
LIKED_STARS = 4  # star ratings at or above this count as a like
DISLIKED_STARS = 2  # star ratings at or below this count as not interested
BECAUSE_YOU_LIKED = "Because you liked {name}"
TAG_YOU_LIKED = "You liked this"
# Short card tag for a place like one the user liked; the liked place's name
# goes in breakdown["similar_to"] (tooltip, reason sentence).
TAG_SIMILAR_PICK = "Similar pick"

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

# Extra "healthy" review words per goal, used only when there is no AI score
# (keyword fallback) and to pick which review a Top picks card shows.
GOAL_HEALTHY_WORDS = {
    "muscle-gain": {"protein", "chicken", "protein-rich"},
    "heart-health": {"heart", "lean", "omega"},
    "less-sugar": {"unsweetened", "sugar-free", "savory"},
    "balanced-diet": {"balanced", "wholesome"},
    "low-carb": {"keto", "low-carb", "bunless"},
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
TAG_HIDDEN_GEM = "Hidden gem"
TAG_ALLERGY_CHECK = "Allergy check"
# Goal tags: for goals the viewer picked (or BMI 25+ -> lighter meals), at
# most MAX_GOAL_TAGS per card, best-fitting first.
GOAL_TAGS = {
    "weight-loss": "Lighter meals",
    "muscle-gain": "High protein",
    "heart-health": "Heart-healthy",
    "less-sugar": "Low sugar",
    "balanced-diet": "Balanced plates",
    "low-carb": "Low carb",
}
GOAL_TAG_MIN = 0.6  # goal fit needed for the tag
# Low carb scores sit low on real reviews (best of 48 places: 0.44), so its
# bar is lower; revisit once more places have reviews.
GOAL_TAG_MIN_BY_GOAL = {"low-carb": 0.4}
HIDDEN_GEM_MIN_STARS = 4.6
HIDDEN_GEM_REVIEWS = (20, 100)  # some reviews, but not many yet
MAX_GOAL_TAGS = 2  # goals overlap a lot; more would push out other tags
MAX_TAGS = 5  # Grade A is not a tag: every Top pick is grade A

# Shown in this order, at most MAX_TAGS: a safety warning first, then the
# viewer's own reasons, then general ones.
TAG_ORDER = (
    TAG_ALLERGY_CHECK,
    "Grade B",
    "Grade C",
    TAG_YOU_LIKED,
    TAG_SIMILAR_PICK,
    TAG_YOUR_FAVORITE,
    *GOAL_TAGS.values(),
    TAG_NEARBY,
    TAG_HEALTHY_REVIEWS,
    TAG_LOWER_CALORIE,
    TAG_HIDDEN_GEM,
    TAG_TOP_RATED,
    TAG_BUDGET,
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


def bmi_weight_loss(profile=None):
    """The viewer's BMI when it should lean picks to lighter meals, else None.

    Only for BMI 25 or more, and not when Muscle gain is picked (BMI can't
    tell muscle from fat) or Weight loss is already picked (counted there).
    """
    if profile is None:
        return None
    goals = normalize_goals(getattr(profile, "health_goals", None))
    if "muscle-gain" in goals or "weight-loss" in goals:
        return None
    value = bmi(
        getattr(profile, "weight_lbs", None), getattr(profile, "height_in", None)
    )
    return value if value is not None and value >= BMI_LEAN_MIN else None


def has_personal_inputs(profile=None, feedback=None):
    """True when the viewer gave us anything personal to score with.

    Decided per viewer (not per place) so every place uses the same weights.
    """
    if feedback is not None and not feedback.is_empty():
        return True
    if profile is None:
        return False
    home_zip, home_boro = home_zip_boro(getattr(profile, "home_address", ""))
    return bool(
        parse_foods(getattr(profile, "favorite_foods", ""))[0]
        or parse_foods(getattr(profile, "disliked_foods", ""))[0]
        or normalize_goals(getattr(profile, "health_goals", None))
        or parse_allergies(getattr(profile, "allergies", ""))
        or home_zip
        or home_boro
        or bmi_weight_loss(profile) is not None
    )


def _weights(personal=False, has_calories=False):
    """Weights in this order: health, grade, rating, [personal], [calorie]."""
    base = PERSONAL_WEIGHTS if personal else DEFAULT_WEIGHTS
    if not has_calories:
        return base
    scale = 1.0 - CALORIE_WEIGHT
    return tuple(w * scale for w in base) + (CALORIE_WEIGHT,)


def _tokenize(text):
    return _WORD_RE.findall((text or "").casefold())


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
    for goal in normalize_goals(getattr(profile, "health_goals", None)):
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


AI_HEALTH_EFFECT = 1.0  # ai score 0..1 -> -0.5..+0.5 (keywords stay -0.3..+0.3)


def health_parts(cuisine, reviews, name, goal_words=(), ai_score=None):
    """The pieces that make up the health component (each added to 0.5).

    cuisine: +0.2 healthy / -0.2 unhealthy cuisine
    reviews: AI score effect, or the keyword share effect when no AI score
    fast_food: -0.2 for fast-food chains
    """
    parts = {"cuisine": 0.0, "reviews": 0.0, "fast_food": 0.0}
    cuisine = (cuisine or "").strip()
    if cuisine in HEALTHY_CUISINES:
        parts["cuisine"] = 0.2
    elif cuisine in UNHEALTHY_CUISINES:
        parts["cuisine"] = -0.2

    if ai_score is not None:
        parts["reviews"] = AI_HEALTH_EFFECT * (float(ai_score) - 0.5)
    else:
        healthy, unhealthy, total = classify_reviews(reviews, goal_words)
        if total:
            parts["reviews"] = 0.3 * ((healthy / total) - (unhealthy / total))

    if is_fast_food(name):
        parts["fast_food"] = -0.2
    return parts


def health_score(cuisine, reviews, name, goal_words=(), ai_score=None):
    """Health component in [0, 1].

    ``ai_score`` is the stored AI health score (0–1) from reviews/menu text.
    When present it replaces the keyword count of the reviews; otherwise the
    keyword method is used.
    """
    parts = health_parts(cuisine, reviews, name, goal_words, ai_score)
    return max(0.0, min(1.0, 0.5 + sum(parts.values())))


# ---------------------------------------------------------------------------
# "Why this pick" sentences: the parts that pushed the score up the most.

REASON_MIN_POINTS = 1.0  # smaller pushes are not worth a sentence
AI_REASON_MIN = 0.6  # AI review score needed to say "healthy food" in a reason
HIGHLY_RATED_MIN = 4.5  # same bar as the Top rated tag
HIGHLY_RATED_MIN_VOTES = 50
MAX_REASONS = 3


def explain_reasons(contributions, max_reasons=MAX_REASONS):
    """Pick the strongest positive reasons and return them as short sentences.

    ``contributions`` is a list of (points, sentence, fallback) where *points*
    is how much that part raised the score compared with an average place.
    Fallback reasons (inspection grade, which every Top pick shares) are only
    used when fewer than two other reasons are strong enough.
    """
    strong = sorted(
        (c for c in contributions if c[0] >= REASON_MIN_POINTS),
        key=lambda c: -c[0],
    )
    main = [sentence for _p, sentence, fallback in strong if not fallback]
    extra = [sentence for _p, sentence, fallback in strong if fallback]
    if len(main) < 2:
        main += extra
    return main[:max_reasons]


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


def _signed(value):
    return f"{value:+.2f}" if round(value, 2) else "0"


def health_steps(h_parts, health, cuisine="", ai_health=None):
    """Lines showing how the health part was worked out (detail page)."""
    raw = 0.5 + sum(h_parts.values())
    if ai_health is not None:
        review_label = f"AI review score {float(ai_health):.2f} (MiniLM)"
    else:
        review_label = "Review keywords (no AI score yet)"
    steps = [
        ("Starting point", "0.50"),
        (f"Cuisine ({cuisine or 'unknown'})", _signed(h_parts["cuisine"])),
        (review_label, _signed(h_parts["reviews"])),
        ("Fast-food chain", _signed(h_parts["fast_food"])),
    ]
    if abs(raw - health) > 1e-9:
        steps.append(("Kept between 0 and 1", f"{raw:.2f} → {health:.2f}"))
    steps.append(("Health", f"{health:.2f}"))
    return steps


def grade_steps(grade):
    """Lines showing how the inspection grade part was worked out."""
    letter = (grade or "").strip().upper()
    return [
        ("Latest posted grade", letter or "none yet"),
        ("Scale", "A = 1.0 · B = 0.5 · C = 0 · other or none = 0.3"),
        ("Grade", f"{grade_score(grade):.2f}"),
    ]


def rating_steps(google_rating, google_count, app_avg, app_count):
    """Lines showing how the rating part was worked out (Bayesian average)."""
    blended, _votes = blended_rating(google_rating, google_count, app_avg, app_count)
    terms = [f"{RATING_PRIOR:.1f} × {RATING_PSEUDO_COUNT}"]
    total = RATING_PSEUDO_COUNT
    steps = []
    try:
        g_rating, g_count = float(google_rating), int(google_count or 0)
    except (TypeError, ValueError):
        g_rating, g_count = None, 0
    if g_rating is not None and g_count > 0:
        steps.append(("Google", f"{g_rating:.1f}★ ({g_count:,} reviews)"))
        terms.append(f"{g_rating:.1f} × {g_count:,}")
        total += g_count
    else:
        steps.append(("Google", "no rating"))
    try:
        a_avg, a_count = float(app_avg), int(app_count or 0)
    except (TypeError, ValueError):
        a_avg, a_count = None, 0
    if a_avg is not None and a_count > 0:
        steps.append(("Our app", f"{a_avg:.1f}★ ({a_count:,} ratings)"))
        terms.append(f"{a_avg:.1f} × {a_count:,}")
        total += a_count
    else:
        steps.append(("Our app", "no ratings yet"))
    steps.append(
        (
            f"Adjusted with {RATING_PSEUDO_COUNT} virtual {RATING_PRIOR:.1f}★ votes",
            f"({' + '.join(terms)}) ÷ {total:,} = {blended:.2f}★",
        )
    )
    score = max(0.0, min(1.0, (blended - 3.0) / 2.0))
    steps.append(("Rating", f"({blended:.2f} − 3.0) ÷ 2 = {score:.2f} (0 to 1)"))
    return steps


def _fit_step(label, delta):
    return (label, f"{delta:+.2f}")


def personal_fit(
    *,
    name,
    cuisine="",
    zipcode="",
    boro="",
    profile=None,
    feedback=None,
    camis="",
    ai_goals=None,
    nutrients=None,
):
    """(fit 0-1, steps, info) for the Personal fit part.

    ``info`` keeps what the tags and reasons need: favorite (FoodOption or
    None), nearby, like_fit, similar_tag, goal_effect, best_goal and
    allergy_warnings (labels of mild allergies common in this cuisine).
    """
    raw = FIT_START
    steps = [("Starting point", f"{FIT_START:.2f}")]
    info = {
        "favorite": None,
        "nearby": False,
        "like_fit": 0.0,
        "similar_tag": None,
        "goal_effect": 0.0,
        "best_goal": "",
        "bmi_effect": 0.0,
        "allergy_warnings": [],
        "goal_tags": [],
    }
    tag_options = []  # (how far above its bar, tag)

    def offer_goal_tag(goal, fit):
        # A tag needs real evidence (reviews or a menu), not the cuisine
        # hint alone.
        field = MENU_NUTRIENTS[goal][0]
        has_source = (ai_goals or {}).get(goal) is not None or (
            bool(nutrients) and field in nutrients
        )
        bar = GOAL_TAG_MIN_BY_GOAL.get(goal, GOAL_TAG_MIN)
        if has_source and fit >= bar:
            tag_options.append((fit - bar, GOAL_TAGS[goal]))

    if profile is not None:
        favorite = first_food_match(
            getattr(profile, "favorite_foods", ""), cuisine, name
        )
        if favorite is not None:
            raw += FIT_FAVORITE
            info["favorite"] = favorite
            steps.append(_fit_step(f"Favorite food: {favorite.label}", FIT_FAVORITE))
        disliked = first_food_match(
            getattr(profile, "disliked_foods", ""), cuisine, name
        )
        if disliked is not None:
            raw += FIT_DISLIKED
            steps.append(_fit_step(f"Disliked food: {disliked.label}", FIT_DISLIKED))

        goals = normalize_goals(getattr(profile, "health_goals", None))
        average, details = goals_fit(goals, cuisine, ai_goals, nutrients)
        if average is not None:
            for goal, (label, fit, goal_steps) in zip(goals, details):
                source = "; ".join(f"{a} {b}" for a, b in goal_steps)
                steps.append((f"Goal: {label} ({source})", f"{fit:.2f}"))
                offer_goal_tag(goal, fit)
            effect = FIT_GOAL_RANGE * (average - 0.5)
            raw += effect
            info["goal_effect"] = effect
            info["best_goal"] = max(details, key=lambda d: d[1])[0]
            steps.append(_fit_step(f"Health goals (average {average:.2f})", effect))

        body_bmi = bmi_weight_loss(profile)
        if body_bmi is not None:
            fit, goal_steps = goal_fit(
                "weight-loss", cuisine, (ai_goals or {}).get("weight-loss"), nutrients
            )
            source = "; ".join(f"{a} {b}" for a, b in goal_steps)
            steps.append(
                (f"Goal: Weight loss, from BMI {body_bmi:.1f} ({source})", f"{fit:.2f}")
            )
            effect = FIT_GOAL_RANGE * BMI_LEAN_SHARE * (fit - 0.5)
            raw += effect
            info["bmi_effect"] = effect
            offer_goal_tag("weight-loss", fit)
            steps.append(_fit_step("BMI 25+ leans to lighter meals (half)", effect))

        for key in mild_allergy_hits(
            parse_allergies(getattr(profile, "allergies", "")), cuisine
        ):
            label = ALLERGY_LABELS[key]
            info["allergy_warnings"].append(label)
            raw += FIT_MILD_ALLERGY
            steps.append(
                _fit_step(f"{label} is common in {cuisine} food", FIT_MILD_ALLERGY)
            )

        home_zip, home_boro = home_zip_boro(getattr(profile, "home_address", ""))
        if (home_zip and home_zip == (zipcode or "").strip()) or (
            home_boro and home_boro.casefold() == (boro or "").strip().casefold()
        ):
            raw += FIT_NEAR_HOME
            info["nearby"] = True
            steps.append(_fit_step("Near your home", FIT_NEAR_HOME))

    if feedback is not None:
        like_fit, cuisine_penalty, tag = feedback_adjustment(cuisine, feedback, camis)
        info["like_fit"], info["similar_tag"] = like_fit, tag
        if like_fit:
            raw += like_fit
            steps.append(_fit_step("Similar to places you liked", like_fit))
        if cuisine_penalty:
            raw += cuisine_penalty
            steps.append(
                _fit_step("Cuisine you marked not interested", cuisine_penalty)
            )

    for _margin, tag in sorted(tag_options, reverse=True):
        if tag not in info["goal_tags"] and len(info["goal_tags"]) < MAX_GOAL_TAGS:
            info["goal_tags"].append(tag)
    fit = max(0.0, min(1.0, raw))
    if abs(raw - fit) > 1e-9:
        steps.append(("Kept between 0 and 1", f"{raw:.2f} → {fit:.2f}"))
    steps.append(("Personal fit", f"{fit:.2f}"))
    return fit, steps, info


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
    ai_health=None,
    ai_goals=None,
    nutrients=None,
):
    """Return (final_score, reason tags, breakdown) for one restaurant.

    ``calorie_score`` is a 0–1 MenuStat median-meal component when linked; omit
    (None) to leave the calorie part out. ``profile`` and ``feedback`` (the
    viewer's FeedbackPrefs: Like / Not interested history) make up the
    Personal fit part; with neither, the score has no Personal fit part.
    ``camis`` keeps a place's own Like from boosting itself. ``ai_health`` is
    the stored AI health score (0–1); None falls back to review keywords.
    ``ai_goals`` ({goal: 0-1}) and ``nutrients`` (MenuStat medians) feed the
    health-goal fit.
    """
    goal_words = _goal_words(profile)
    h_parts = health_parts(cuisine, reviews, name, goal_words, ai_score=ai_health)
    h = max(0.0, min(1.0, 0.5 + sum(h_parts.values())))
    g = grade_score(grade)
    r = rating_score(google_rating, google_count, app_avg, app_count)
    has_calories = calorie_score is not None
    personal = has_personal_inputs(profile, feedback)
    weights = list(_weights(personal, has_calories=has_calories))
    w_h, w_g, w_r = weights[:3]
    w_p = weights[3] if personal else None
    w_c = weights[-1] if has_calories else None
    c = max(0.0, min(1.0, float(calorie_score))) if has_calories else None

    p, p_steps, info = None, [], {}
    if personal:
        p, p_steps, info = personal_fit(
            name=name,
            cuisine=cuisine,
            zipcode=zipcode,
            boro=boro,
            profile=profile,
            feedback=feedback,
            camis=camis,
            ai_goals=ai_goals,
            nutrients=nutrients,
        )
    score = 100.0 * (h * w_h + g * w_g + r * w_r)
    if personal:
        score += 100.0 * p * w_p
    if has_calories:
        score += 100.0 * c * w_c

    favorite = info.get("favorite")
    is_favorite = favorite is not None
    is_nearby = bool(info.get("nearby"))
    # Points the likes add (pick_top lets only one pick use them).
    like_bonus = 100.0 * w_p * info["like_fit"] if personal else 0.0
    liked_tag = info.get("similar_tag")

    healthy_n, _unhealthy_n, total = classify_reviews(reviews, goal_words)
    blended, vote_count = blended_rating(
        google_rating, google_count, app_avg, app_count
    )

    candidates = []
    if info.get("allergy_warnings"):
        candidates.append(TAG_ALLERGY_CHECK)
    if (grade or "").strip().upper() in ("B", "C"):
        candidates.append(f"Grade {(grade or '').strip().upper()}")
    candidates.extend(info.get("goal_tags", []))
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
    try:
        g_stars, g_count = float(google_rating or 0), int(google_count or 0)
    except (TypeError, ValueError):
        g_stars, g_count = 0.0, 0
    low, high = HIDDEN_GEM_REVIEWS
    if g_stars >= HIDDEN_GEM_MIN_STARS and low <= g_count < high:
        candidates.append(TAG_HIDDEN_GEM)
    elif vote_count >= 50 and blended >= 4.5:
        candidates.append(TAG_TOP_RATED)

    similar_to = ""
    if liked_tag == TAG_YOU_LIKED:
        candidates.append(liked_tag)
    elif liked_tag:
        similar_to = liked_tag.replace("Because you liked ", "")
        candidates.append(TAG_SIMILAR_PICK)
    # The card shows the grade only through tags (no photo badge), so B and C
    # are tags; A is not (every Top pick is grade A).
    tags = [tag for tag in TAG_ORDER if tag in candidates][:MAX_TAGS]

    def _part(key, label, value, weight, steps=()):
        return {
            "key": key,
            "label": label,
            "value_0_1": value,
            "weight": weight,
            "weight_pct": weight * 100.0,
            "points": 100.0 * value * weight,
            "steps": list(steps),  # how the 0-1 value came about (detail page)
        }

    parts = [
        _part(
            "health",
            "Health (AI)" if ai_health is not None else "Health",
            h,
            w_h,
            health_steps(h_parts, h, cuisine, ai_health),
        ),
        _part("grade", "Inspection grade", g, w_g, grade_steps(grade)),
        _part(
            "rating",
            "Rating",
            r,
            w_r,
            rating_steps(google_rating, google_count, app_avg, app_count),
        ),
    ]
    if personal:
        parts.append(_part("personal", "Personal fit", p, w_p, p_steps))
    if has_calories:
        parts.append(
            _part(
                "calories",
                "Menu calories",
                c,
                w_c,
                [("Lighter typical meal on MenuStat = higher", f"{c:.2f}")],
            )
        )

    # Why this pick: how much each part raised the score vs. an average place
    # (every part at 0.5).
    contributions = []
    if h_parts["cuisine"] > 0:
        contributions.append(
            (100 * w_h * h_parts["cuisine"], f"Healthy cuisine ({cuisine})", False)
        )
    # Only claim "healthy reviews" on a clear signal, not a score just above 0.5.
    if ai_health is not None and float(ai_health) >= AI_REASON_MIN:
        contributions.append(
            (
                100 * w_h * h_parts["reviews"],
                "Reviews describe fresh, healthy food",
                False,
            )
        )
    elif ai_health is None and TAG_HEALTHY_REVIEWS in candidates:
        contributions.append(
            (100 * w_h * h_parts["reviews"], "Reviews mention healthy dishes", False)
        )
    if c is not None:
        contributions.append((100 * w_c * (c - 0.5), "Lighter menu choices", False))
    highly_rated = blended >= HIGHLY_RATED_MIN and vote_count >= HIGHLY_RATED_MIN_VOTES
    if google_rating and google_count and highly_rated:
        contributions.append(
            (
                100 * w_r * (r - 0.5),
                f"Highly rated ({float(google_rating):.1f}★, "
                f"{int(google_count):,} reviews)",
                False,
            )
        )
    if is_favorite:
        contributions.append(
            (
                100 * w_p * FIT_FAVORITE,
                f"Matches your favorite food ({favorite.label})",
                False,
            )
        )
    if personal and info["goal_effect"] > 0:
        contributions.append(
            (
                100 * w_p * info["goal_effect"],
                f"Fits your goal: {info['best_goal']}",
                False,
            )
        )
    if personal and info["bmi_effect"] > 0:
        contributions.append(
            (100 * w_p * info["bmi_effect"], "Lighter meals, based on your BMI", False)
        )
    if is_nearby:
        contributions.append((100 * w_p * FIT_NEAR_HOME, "Near your home", False))
    if like_bonus and similar_to:
        contributions.append(
            (like_bonus, f"Similar to {similar_to}, which you liked", False)
        )
    if (grade or "").strip().upper() == "A":
        contributions.append((100 * w_g * (g - 0.5), "NYC health grade A", True))
    reasons = explain_reasons(contributions)

    breakdown = {
        "mode": "personal" if personal else "default",
        "has_calories": has_calories,
        "ai_health": ai_health,
        "health_parts": h_parts,
        "reasons": reasons,
        "reason_text": " · ".join(reasons),
        "parts": parts,
        "allergy_warnings": info.get("allergy_warnings", []),
        "total": score,
        "tags": tags,
        "like_bonus": like_bonus,
        "similar_to": similar_to,
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
