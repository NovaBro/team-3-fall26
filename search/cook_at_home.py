"""Cook-at-home suggestions when mood and energy are both high.

Separate from restaurant ``score_restaurant`` / ``mood_overlay``:
high mood + high energy unlocks farmers markets and Shop Healthy stores on
the home page so users can cook healthier meals at home.

Only places with Google enrichment of at least 4.0 stars and 100 reviews are
eligible (strict: missing enrichment is excluded).
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from django.db.models import Max
from django.urls import reverse

from accounts.mood import today_ny
from community.keys import FARMERS_MARKET, GROCERY, farmers_market_key, grocery_key
from community.models import PlaceEnrichment
from search.find_food import BOROUGH_ALIASES, market_operates_on_day
from search.forms import FARMERS_MARKET as FM_TYPE
from search.forms import GROCERY as GROCERY_TYPE
from search.forms import MARKET_DAYS
from search.models import FarmersMarket, HealthyStore
from search.recommend import ENERGY_HIGH, MOOD_HIGH, daily_sample, daily_seed

MIN_STORE_RATING = 4.0
MIN_STORE_REVIEWS = 100


def is_cook_at_home_check_in(check_in) -> bool:
    """True when today's mood and energy are both at least 4."""
    if check_in is None:
        return False
    mood = getattr(check_in, "mood", None)
    energy = getattr(check_in, "energy_level", None)
    if mood is None or energy is None:
        return False
    return int(mood) >= MOOD_HIGH and int(energy) >= ENERGY_HIGH


def passes_place_quality(rating, review_count) -> bool:
    """True when Google rating and review count meet cook-at-home minimums."""
    if rating is None or review_count is None:
        return False
    try:
        stars = float(rating)
        reviews = int(review_count)
    except (TypeError, ValueError):
        return False
    return stars >= MIN_STORE_RATING and reviews >= MIN_STORE_REVIEWS


def _boroughs(area: str) -> list[str]:
    area = (area or "").strip()
    if not area:
        return []
    return BOROUGH_ALIASES.get(area, [area])


def _today_weekday(day: date | None = None) -> str:
    when = day or today_ny()
    # MARKET_DAYS is Monday..Sunday; date.weekday() is Mon=0.
    return MARKET_DAYS[when.weekday()]


def _enrichment_map(kind: str, keys: list[str]) -> dict:
    """key -> (rating, user_rating_count) for the given kind."""
    if not keys:
        return {}
    rows = PlaceEnrichment.objects.filter(kind=kind, key__in=keys).values_list(
        "key", "rating", "user_rating_count"
    )
    return {key: (rating, count) for key, rating, count in rows}


def _market_dict(market: FarmersMarket) -> dict:
    return {
        "kind": FARMERS_MARKET,
        "name": market.market_name or "(no name)",
        "address": market.street_address or "",
        "borough": market.borough or "",
        "days": market.days_of_operation or "",
        "hours": market.hours_of_operations or "",
        "lat": market.latitude,
        "lng": market.longitude,
        "year_awarded": None,
    }


def _store_dict(store: HealthyStore) -> dict:
    borough = store.borough or ""
    if borough == "New York":
        borough = "Manhattan"
    return {
        "kind": GROCERY,
        "name": store.store_name or "(no name)",
        "address": store.street_address or "",
        "borough": borough,
        "days": "",
        "hours": "",
        "lat": store.latitude,
        "lng": store.longitude,
        "year_awarded": store.year_awarded,
    }


def _quality_markets(markets: list[FarmersMarket]) -> list[FarmersMarket]:
    keys = [
        farmers_market_key(m.year, m.market_name, m.street_address) for m in markets
    ]
    enrich = _enrichment_map(FARMERS_MARKET, keys)
    kept = []
    for market, key in zip(markets, keys):
        rating, count = enrich.get(key, (None, None))
        if passes_place_quality(rating, count):
            kept.append(market)
    return kept


def _quality_stores(stores: list[HealthyStore]) -> list[HealthyStore]:
    keys = [grocery_key(s.store_name, s.street_address, s.zip_code) for s in stores]
    enrich = _enrichment_map(GROCERY, keys)
    kept = []
    for store, key in zip(stores, keys):
        rating, count = enrich.get(key, (None, None))
        if passes_place_quality(rating, count):
            kept.append(store)
    return kept


def _sample_markets(boro: str, count: int, seed: str, day: date) -> list[dict]:
    latest_year = FarmersMarket.pool.aggregate(latest=Max("year"))["latest"]
    if latest_year is None or count <= 0:
        return []
    qs = FarmersMarket.pool.filter(year=latest_year).order_by(
        "market_name", "borough", "street_address"
    )
    boroughs = _boroughs(boro)
    if boroughs:
        qs = qs.filter(borough__in=boroughs)
    markets = _quality_markets(list(qs))
    if not markets:
        return []

    weekday = _today_weekday(day)
    open_today = [
        m for m in markets if market_operates_on_day(m.days_of_operation, weekday)
    ]
    open_ids = {m.pk for m in open_today}
    rest = [m for m in markets if m.pk not in open_ids]
    # Prefer markets open today; fill from the rest with a stable daily sample.
    chosen = list(daily_sample(open_today, min(count, len(open_today)), seed + ":open"))
    if len(chosen) < count:
        need = count - len(chosen)
        chosen.extend(daily_sample(rest, min(need, len(rest)), seed + ":rest"))
    return [_market_dict(m) for m in chosen]


def _sample_stores(boro: str, count: int, seed: str) -> list[dict]:
    if count <= 0:
        return []
    qs = HealthyStore.pool.order_by("store_name", "street_address")
    boroughs = _boroughs(boro)
    if boroughs:
        qs = qs.filter(borough__in=boroughs)
    stores = _quality_stores(list(qs))
    if not stores:
        return []
    return [_store_dict(s) for s in daily_sample(stores, min(count, len(stores)), seed)]


def cook_at_home_picks(
    boro: str = "",
    *,
    market_count: int = 2,
    store_count: int = 2,
    day: date | None = None,
    user_id=None,
) -> dict:
    """Return ``{"markets": [...], "stores": [...]}`` for the cook-at-home strip.

    ``boro`` is a Find-food / home borough label (e.g. ``Brooklyn``). Empty means
    citywide. Sampling is stable for the NY calendar day (+ optional user id).
    Only places with Google enrichment of at least ``MIN_STORE_RATING`` stars and
    ``MIN_STORE_REVIEWS`` reviews are included.
    """
    when = day or today_ny()
    seed = daily_seed(when, user_id)
    area = (boro or "").strip()
    return {
        "markets": _sample_markets(area, market_count, seed + ":markets", when),
        "stores": _sample_stores(area, store_count, seed + ":stores"),
    }


def find_food_cook_url(boro: str = "") -> str:
    """Find food URL pre-filtered to farmers markets + Shop Healthy stores."""
    query = [("types", FM_TYPE), ("types", GROCERY_TYPE)]
    area = (boro or "").strip()
    if area:
        query.append(("area", area))
    return f"{reverse('search:index')}?{urlencode(query)}"
