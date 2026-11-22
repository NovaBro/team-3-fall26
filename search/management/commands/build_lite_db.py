"""Build database/nyc_food_lite.db: a small, fast copy of the full dataset DB.

The full nyc_food.db holds ~31.5K restaurants and ~297K inspection rows, which
makes Top Picks, tab switches, and search slow. This command copies it and keeps
only the best places per type (default 500 each):

- restaurants: spread across boroughs, ranked by a Bayesian-average Google
  rating (rating pulled toward the mean when there are few reviews); places
  without Google data fill any remaining slots (grade A first, then newest)
- Shop Healthy grocery stores and farmers markets (per year): same ranking

Places Google marks as closed are dropped. The full nyc_food.db and community.db
are only read, never changed. Settings use the lite file when it exists; set
NYCFOOD_FULL_DATA=1 to use the full DB instead.

    python manage.py build_lite_db [--limit 500] [--force]
"""

import os
import sqlite3
from collections import Counter, defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from community.keys import (
    DOHMH,
    FARMERS_MARKET,
    GROCERY,
    dohmh_key,
    farmers_market_key,
    grocery_key,
)

BOROUGHS = ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")
CLOSED = {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"}
PRIOR_REVIEWS = 50  # reviews needed before a place's own rating dominates
BOROUGH_MINIMUM = 40  # restaurants kept per borough, when available


def bayes_score(rating, count, prior_mean, prior_reviews=PRIOR_REVIEWS):
    """Rating pulled toward prior_mean when there are few reviews; None if no data."""
    if rating is None or not count:
        return None
    return (count * rating + prior_reviews * prior_mean) / (count + prior_reviews)


def prior_mean(enrichment):
    """Mean Google rating over an enrichment map (key -> (rating, count, status))."""
    ratings = [r for r, _count, _status in enrichment.values() if r is not None]
    return sum(ratings) / len(ratings) if ratings else 0.0


def is_closed(enrichment, key):
    return key in enrichment and enrichment[key][2] in CLOSED


def score_for(enrichment, key, mean):
    rating, count, _status = enrichment.get(key, (None, None, ""))
    return bayes_score(rating, count, mean)


def borough_quotas(counts, limit, minimum=BOROUGH_MINIMUM):
    """Split ``limit`` across boroughs: a floor each, the rest proportional.

    ``counts`` maps borough -> number of candidates; no quota exceeds its count.
    Extra slots go one at a time to the borough with the highest
    count / (quota + 1) (D'Hondt), which tracks each borough's share.
    """
    boroughs = [b for b, c in counts.items() if c > 0]
    if not boroughs or limit <= 0:
        return {}
    floor = min(minimum, limit // len(boroughs))
    quotas = {b: min(floor, counts[b]) for b in boroughs}
    remaining = limit - sum(quotas.values())
    while remaining > 0:
        open_ = [b for b in boroughs if quotas[b] < counts[b]]
        if not open_:
            break
        best = max(open_, key=lambda b: (counts[b] / (quotas[b] + 1), b))
        quotas[best] += 1
        remaining -= 1
    return quotas


def pick_restaurants(rows, enrichment, limit, minimum=BOROUGH_MINIMUM):
    """Choose up to ``limit`` camis values from RestaurantSummary-like rows.

    ``rows``: dicts with camis, boro, latest_grade, last_date (ISO string/None).
    ``enrichment``: dohmh_key(camis) -> (rating, user_rating_count, status).
    """
    mean = prior_mean(enrichment)
    by_boro = defaultdict(list)
    for row in rows:
        key = dohmh_key(row["camis"])
        if row["boro"] not in BOROUGHS or row["latest_grade"] == "C":
            continue
        if is_closed(enrichment, key):
            continue
        by_boro[row["boro"]].append((score_for(enrichment, key, mean), row))

    def rank(item):
        score, row = item
        return (
            score is not None,
            score or 0.0,
            row["latest_grade"] == "A",
            row["last_date"] or "",
            row["camis"],
        )

    quotas = borough_quotas({b: len(v) for b, v in by_boro.items()}, limit, minimum)
    kept = []
    for boro, quota in quotas.items():
        best = sorted(by_boro[boro], key=rank, reverse=True)[:quota]
        kept.extend(row["camis"] for _score, row in best)
    return kept


def pick_ranked(items, enrichment, limit):
    """Top ``limit`` ids from (id, key) pairs by Google score; unrated last."""
    mean = prior_mean(enrichment)
    scored = [
        (score_for(enrichment, key, mean), item_id)
        for item_id, key in items
        if not is_closed(enrichment, key)
    ]
    scored.sort(key=lambda s: (s[0] is not None, s[0] or 0.0, -s[1]), reverse=True)
    return [item_id for _score, item_id in scored[:limit]]


def load_enrichment(conn, kind):
    rows = conn.execute(
        "SELECT key, rating, user_rating_count, business_status "
        "FROM community_placeenrichment WHERE kind = ?",
        (kind,),
    )
    return {key: (rating, count, status or "") for key, rating, count, status in rows}


def _keep_only(conn, table, column, values):
    conn.execute("DROP TABLE IF EXISTS temp.lite_keep")
    conn.execute("CREATE TEMP TABLE lite_keep (value PRIMARY KEY)")
    conn.executemany(
        "INSERT OR IGNORE INTO temp.lite_keep VALUES (?)", [(v,) for v in values]
    )
    conn.execute(
        f'DELETE FROM "{table}" WHERE "{column}" NOT IN '
        "(SELECT value FROM temp.lite_keep)"
    )


class Command(BaseCommand):
    help = "Copy nyc_food.db to a small lite DB with the best places per type."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--source", default=str(settings.FULL_DB_PATH))
        parser.add_argument(
            "--community", default=str(settings.DATABASES["community"]["NAME"])
        )
        parser.add_argument("--dest", default=str(settings.LITE_DB_PATH))

    def handle(self, *args, limit, force, source, community, dest, **options):
        if os.path.abspath(source) == os.path.abspath(dest):
            raise CommandError("--dest must differ from --source.")
        if not os.path.exists(source):
            raise CommandError(f"Full database not found: {source}")
        if os.path.exists(dest) and not force:
            raise CommandError(
                f"{dest} exists. Rebuilding replaces it (accounts created while "
                "using it are lost); pass --force to continue."
            )

        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        if os.path.exists(community):
            src.execute(
                "ATTACH DATABASE ? AS community", (f"file:{community}?mode=ro",)
            )
            restaurants = load_enrichment(src, DOHMH)
            groceries = load_enrichment(src, GROCERY)
            markets = load_enrichment(src, FARMERS_MARKET)
        else:
            self.stderr.write("community.db not found; ranking without Google data.")
            restaurants = groceries = markets = {}

        camis = pick_restaurants(
            [
                dict(r)
                for r in src.execute(
                    "SELECT camis, boro, latest_grade, last_date "
                    "FROM search_restaurantsummary"
                )
            ],
            restaurants,
            limit,
        )
        store_ids = pick_ranked(
            [
                (
                    r["id"],
                    grocery_key(r["store_name"], r["street_address"], r["zip_code"]),
                )
                for r in src.execute(
                    "SELECT id, store_name, street_address, zip_code "
                    "FROM search_healthystore"
                )
            ],
            groceries,
            limit,
        )
        by_year = defaultdict(list)
        for r in src.execute(
            "SELECT id, year, market_name, street_address FROM search_farmersmarket"
        ):
            key = farmers_market_key(r["year"], r["market_name"], r["street_address"])
            by_year[r["year"]].append((r["id"], key))
        kept_by_year = {
            year: pick_ranked(items, markets, limit) for year, items in by_year.items()
        }
        market_ids = [i for ids in kept_by_year.values() for i in ids]
        years = [y for y in kept_by_year if y is not None]
        latest_markets = len(kept_by_year[max(years)]) if years else 0

        tmp = f"{dest}.building"
        if os.path.exists(tmp):
            os.remove(tmp)
        out = sqlite3.connect(tmp)
        src.backup(out)
        src.close()
        with out:
            _keep_only(out, "search_restaurantinspection", "camis", camis)
            _keep_only(out, "search_restaurantsummary", "camis", camis)
            _keep_only(out, "search_healthystore", "id", store_ids)
            _keep_only(out, "search_farmersmarket", "id", market_ids)
            out.execute("DROP TABLE temp.lite_keep")
        out.execute("VACUUM")
        out.close()
        os.replace(tmp, dest)

        check = sqlite3.connect(dest)
        per_boro = Counter(
            row[0] for row in check.execute("SELECT boro FROM search_restaurantsummary")
        )
        check.close()
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {dest}: {len(camis)} restaurants "
                f"({', '.join(f'{b} {n}' for b, n in per_boro.most_common())}), "
                f"{len(store_ids)} grocery stores, {latest_markets} farmers markets "
                f"in the latest year ({len(market_ids)} market rows, all years)."
            )
        )
