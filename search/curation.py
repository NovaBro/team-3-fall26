"""Choose which places stay in the ranked pool (the ``active`` flag).

Ranking, Find food and the assistant read ``Model.pool`` (active rows only).
Nothing is deleted: Google data cost money, so places that drop out keep their
rows, enrichment and reviews and can come back on the next run.

Per category and per borough, places are ordered by a weighted rating

    score = (v * R + m * C) / (v + m)

where R is the Google rating, v its review count, C the category's mean rating
and m a prior (review count at which the place's own rating counts half). A
4.9 with 3 reviews therefore ranks below a 4.6 with 2,000. The top
``per_borough`` eligible places are kept.

Eligibility:
- Restaurants: Google says OPERATIONAL, rating >= 3.5, at least 20 reviews.
- Farmers markets (latest season only) and Shop Healthy stores: kept unless
  Google lists them as permanently closed, or rates them below 3.5 on at least
  5 reviews. Unrated ones rank after every rated one.
"""

from collections import defaultdict
from dataclasses import dataclass

from django.db import router, transaction
from django.db.models import Max

from community.keys import (
    FARMERS_MARKET,
    GROCERY,
    farmers_market_key,
    grocery_key,
)
from community.models import PlaceEnrichment, Restaurant
from search.models import FarmersMarket, HealthyStore

PER_BOROUGH = 500
MIN_RATING = 3.5
RESTAURANT_MIN_REVIEWS = 20
# Markets and stores get few reviews; below this a low rating isn't trusted.
PLACE_MIN_REVIEWS = 5
RESTAURANT_PRIOR = 100
PLACE_PRIOR = 20
CLOSED = "CLOSED_PERMANENTLY"

RESTAURANTS = "restaurants"
MARKETS = "markets"
STORES = "stores"
KINDS = (RESTAURANTS, MARKETS, STORES)


@dataclass
class Candidate:
    pk: object
    borough: str
    rating: float | None
    count: int
    eligible: bool


def weighted_rating(rating, count, mean, prior):
    if rating is None or not count:
        return None
    return (count * rating + prior * mean) / (count + prior)


def select(candidates, per_borough, prior):
    """Primary keys of the top ``per_borough`` eligible candidates per borough."""
    rated = [c for c in candidates if c.eligible and c.rating is not None and c.count]
    mean = sum(c.rating for c in rated) / len(rated) if rated else 0.0
    by_borough = defaultdict(list)
    for c in candidates:
        if c.eligible:
            by_borough[c.borough].append(c)
    kept = set()
    for group in by_borough.values():

        def order(c):
            score = weighted_rating(c.rating, c.count, mean, prior)
            return (score is None, -(score or 0), -c.count, str(c.pk))

        kept.update(c.pk for c in sorted(group, key=order)[:per_borough])
    return kept


def restaurant_candidates():
    rows = Restaurant.objects.values_list(
        "place_id", "boro", "rating", "rating_count", "business_status"
    )
    return [
        Candidate(
            pk=place_id,
            borough=boro,
            rating=rating,
            count=count or 0,
            eligible=bool(boro)
            and status == Restaurant.OPERATIONAL
            and rating is not None
            and rating >= MIN_RATING
            and (count or 0) >= RESTAURANT_MIN_REVIEWS,
        )
        for place_id, boro, rating, count, status in rows
    ]


def _google_ratings(kind):
    """{key: (rating, review count, business status)} for one enrichment kind."""
    rows = PlaceEnrichment.objects.filter(kind=kind).values_list(
        "key", "rating", "user_rating_count", "business_status"
    )
    return {key: (rating, count or 0, status) for key, rating, count, status in rows}


def _place_candidate(pk, borough, google, eligible=True):
    rating, count, status = google or (None, 0, "")
    trusted_low = rating is not None and rating < MIN_RATING
    trusted_low = trusted_low and count >= PLACE_MIN_REVIEWS
    return Candidate(
        pk=pk,
        borough=borough,
        rating=rating,
        count=count,
        eligible=eligible and status != CLOSED and not trusted_low,
    )


def market_candidates():
    ratings = _google_ratings(FARMERS_MARKET)
    latest = FarmersMarket.objects.aggregate(latest=Max("year"))["latest"]
    return [
        _place_candidate(
            m.pk,
            m.borough,
            ratings.get(farmers_market_key(m.year, m.market_name, m.street_address)),
            eligible=m.year == latest,
        )
        for m in FarmersMarket.objects.all()
    ]


def store_candidates():
    ratings = _google_ratings(GROCERY)
    return [
        _place_candidate(
            s.pk,
            s.borough,
            ratings.get(grocery_key(s.store_name, s.street_address, s.zip_code)),
        )
        for s in HealthyStore.objects.all()
    ]


CATEGORIES = {
    RESTAURANTS: (Restaurant, restaurant_candidates, RESTAURANT_PRIOR),
    MARKETS: (FarmersMarket, market_candidates, PLACE_PRIOR),
    STORES: (HealthyStore, store_candidates, PLACE_PRIOR),
}


def curate(kinds=KINDS, per_borough=PER_BOROUGH, dry_run=False):
    """Set ``active`` on each category; returns {kind: {borough: (kept, total)}}."""
    report = {}
    for kind in kinds:
        model, candidates_for, prior = CATEGORIES[kind]
        candidates = candidates_for()
        kept = select(candidates, per_borough, prior)
        counts = defaultdict(lambda: [0, 0])
        for c in candidates:
            counts[c.borough][1] += 1
            counts[c.borough][0] += c.pk in kept
        report[kind] = {b: tuple(v) for b, v in sorted(counts.items())}
        if not dry_run:
            with transaction.atomic(using=router.db_for_write(model)):
                model.objects.exclude(pk__in=kept).update(active=False)
                model.objects.filter(pk__in=kept).update(active=True)
    return report
