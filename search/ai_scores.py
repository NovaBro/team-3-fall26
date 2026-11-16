"""AI health scores for restaurants, worked out when they are needed.

A restaurant's score comes from its review text (plus menu text for MenuStat
chains), read by the MiniLM model in ``search/health_ai.py``. The first time a
place is scored (a Top picks candidate, or a detail page) the score is
computed and stored in ``community.HealthScore``; later visits read it.
``python manage.py score_health`` can still fill many places ahead of time.

If the model can't load, or there is no health-related text, the caller falls
back to the review-keyword count, as before.
"""

import logging
import threading
import time

from django.conf import settings
from django.core.cache import cache
from django.db.models import Max

from community.models import HealthScore
from search import health_ai
from search.menustat import MEAL_CATEGORIES, match_menustat_restaurant
from search.models import MenuItem

logger = logging.getLogger(__name__)

NO_TEXT_SECONDS = 60 * 60  # a place with no usable text is retried after this
RETRY_LOAD_SECONDS = 10 * 60  # after the model failed to load

_lock = threading.Lock()
_encoder = None
_failed_at = None


def menu_texts(name):
    """Meal names and descriptions of a MenuStat chain, or []."""
    chain = match_menustat_restaurant(name)
    if not chain:
        return []
    latest = MenuItem.objects.filter(restaurant=chain).aggregate(y=Max("year"))["y"]
    rows = MenuItem.objects.filter(
        restaurant=chain, year=latest, food_category__in=MEAL_CATEGORIES
    ).values_list("item_name", "item_description")
    return [f"{item}. {desc}".strip() for item, desc in rows if item]


def shared_encoder():
    """One encoder per process, loaded on first use; None if it can't load."""
    global _encoder, _failed_at
    if _encoder is not None:
        return _encoder
    if _failed_at is not None and time.monotonic() - _failed_at < RETRY_LOAD_SECONDS:
        return None
    with _lock:
        if _encoder is None:
            try:
                _encoder = health_ai.load_encoder(health_ai.MODEL_NAME)
                _failed_at = None
            except Exception:
                logger.warning("AI health model could not load", exc_info=True)
                _failed_at = time.monotonic()
                return None
    return _encoder


def stored_score(camis):
    if not camis:
        return None
    return (
        HealthScore.objects.filter(camis=str(camis))
        .values_list("score", flat=True)
        .first()
    )


def ai_scores_for(camis, name="", review_texts=()):
    """(health 0-1 or None, {goal: 0-1}) for a restaurant, computing if needed.

    Stored scores are reused. A place with no row, or a row made before goal
    scores existed, is scored from the given review text (and menu text) when
    AI_LIVE_SCORING is on, and the result is stored. (None, {}) when it can't
    be worked out (no text about food health, or no model).
    """
    if not camis:
        return None, {}
    row = (
        HealthScore.objects.filter(camis=str(camis))
        .values_list("score", "goal_scores")
        .first()
    )
    if row is not None and row[1] is not None:
        return row[0], row[1]
    stored_health = row[0] if row is not None else None
    if not getattr(settings, "AI_LIVE_SCORING", False):
        return stored_health, {}
    texts = [t for t in review_texts if (t or "").strip()]
    if not texts:
        return stored_health, {}  # nothing to read yet; try again later
    no_text_key = f"ai-health-none:{camis}:{len(texts)}"
    if cache.get(no_text_key):
        return stored_health, {}
    encoder = shared_encoder()
    if encoder is None:
        return stored_health, {}
    try:
        health, used, goals = health_ai.all_scores(texts + menu_texts(name), encoder)
    except Exception:
        logger.warning("AI health score failed for %s", camis, exc_info=True)
        return stored_health, {}
    if health is None:
        cache.set(no_text_key, True, NO_TEXT_SECONDS)
        return stored_health, {}
    HealthScore.objects.update_or_create(
        camis=str(camis),
        defaults={
            "score": health,
            "sentences_used": used,
            "goal_scores": goals,
            "model_name": health_ai.MODEL_NAME,
        },
    )
    return health, goals


def ai_health_for(camis, name="", review_texts=()):
    """AI health score (0-1) for a restaurant, or None (see ai_scores_for)."""
    return ai_scores_for(camis, name, review_texts)[0]
