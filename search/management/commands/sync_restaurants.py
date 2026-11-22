"""Keep the Google-backed restaurant pool (community.Restaurant) filled.

Two jobs, both on by default:

- **Refresh**: re-fetch active restaurants (the curated pool) whose data is
  older than ``--max-age-days`` (default 30, the longest Google lets
  coordinates be cached). One Place Details request each; also refreshes
  their reviews. Inactive places are not refreshed, which saves requests.
- **Discover**: Text Search for every borough x cuisine pair (e.g. "thai
  restaurants in Queens, NY"), following up to ``--pages`` result pages of 20.
  New places are added; known ones are updated. No reviews (cheaper).

After a real run the pool is re-curated (``curate_pool``), so new places only
stay active if they rank in their borough's top 500.

``--limit`` caps the total number of Google requests, so a run never costs
more than expected. Every request is billed; check your Google Cloud budget.

Usage:
    python manage.py sync_restaurants --limit 200 --sleep 0.2
    python manage.py sync_restaurants --discover-only --boro Queens --pages 1
    python manage.py sync_restaurants --refresh-only --max-age-days 14
    python manage.py sync_restaurants --place-id ChIJ...   # one place
    python manage.py sync_restaurants --dry-run            # show the plan
"""

import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from community.models import Restaurant
from restaurants.boroughs import BOROUGHS
from search.curation import RESTAURANTS, curate
from search.services.places import (
    PlacesAPIError,
    enrich_place_id,
    restaurant_fields,
    save_restaurant,
    search_restaurants,
)

# Search terms for discovery: one query per term and borough. Plain
# "restaurants" catches places whose cuisine has no term here.
DISCOVERY_TERMS = (
    "restaurants",
    "healthy restaurants",
    "salad",
    "vegetarian restaurants",
    "vegan restaurants",
    "american restaurants",
    "chinese restaurants",
    "japanese restaurants",
    "korean restaurants",
    "thai restaurants",
    "vietnamese restaurants",
    "indian restaurants",
    "mexican restaurants",
    "latin american restaurants",
    "caribbean restaurants",
    "italian restaurants",
    "pizza",
    "mediterranean restaurants",
    "middle eastern restaurants",
    "greek restaurants",
    "french restaurants",
    "seafood restaurants",
    "sandwich shops",
    "juice bars",
)


class Budget:
    """Counts Google requests against ``--limit`` (None = no cap)."""

    def __init__(self, limit):
        self.limit = limit
        self.used = 0

    def take(self):
        if self.limit is not None and self.used >= self.limit:
            return False
        self.used += 1
        return True


class Command(BaseCommand):
    help = "Refresh and discover NYC restaurants from Google Places."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, help="Max Google requests.")
        parser.add_argument("--sleep", type=float, default=0.0)
        parser.add_argument("--max-age-days", type=int, default=30)
        parser.add_argument("--pages", type=int, default=3, help="Pages per query.")
        parser.add_argument(
            "--boro", action="append", choices=BOROUGHS, dest="boroughs"
        )
        parser.add_argument("--term", action="append", dest="terms")
        parser.add_argument("--place-id", action="append", dest="place_ids")
        parser.add_argument("--refresh-only", action="store_true")
        parser.add_argument("--discover-only", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be a positive integer.")
        if options["refresh_only"] and options["discover_only"]:
            raise CommandError("Choose at most one of --refresh-only, --discover-only.")
        self.options = options
        self.budget = Budget(options["limit"])

        if options["place_ids"]:
            self._refresh(options["place_ids"])
        else:
            if not options["discover_only"]:
                self._refresh(self._stale_place_ids())
            if not options["refresh_only"]:
                self._discover()
        if not options["dry_run"]:
            curate(kinds=(RESTAURANTS,))
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {self.budget.used} Google requests; "
                f"{Restaurant.objects.count()} restaurants stored, "
                f"{Restaurant.pool.count()} active."
            )
        )

    def _pause(self):
        if self.options["sleep"]:
            time.sleep(self.options["sleep"])

    def _stale_place_ids(self):
        cutoff = timezone.now() - timedelta(days=self.options["max_age_days"])
        return list(
            Restaurant.pool.filter(fetched_at__lt=cutoff)
            .order_by("fetched_at")
            .values_list("place_id", flat=True)
        )

    def _refresh(self, place_ids):
        self.stdout.write(f"=== refresh: {len(place_ids)} places ===")
        if self.options["dry_run"]:
            return
        done = failed = 0
        for place_id in place_ids:
            if not self.budget.take():
                self.stdout.write("Request limit reached.")
                break
            try:
                enrich_place_id(place_id)
            except PlacesAPIError as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"{place_id}: {exc}"))
            else:
                done += 1
            self._pause()
        self.stdout.write(f"Refreshed {done}, failed {failed}.")

    def _queries(self):
        terms = self.options["terms"] or DISCOVERY_TERMS
        boroughs = self.options["boroughs"] or BOROUGHS
        return [f"{term} in {boro}, NY" for boro in boroughs for term in terms]

    def _discover(self):
        queries = self._queries()
        self.stdout.write(f"=== discover: {len(queries)} queries ===")
        if self.options["dry_run"]:
            for query in queries:
                self.stdout.write(f"  {query}")
            return
        known = set(Restaurant.objects.values_list("place_id", flat=True))
        added = updated = 0
        for query in queries:
            token = ""
            for _page in range(max(1, self.options["pages"])):
                if not self.budget.take():
                    self.stdout.write("Request limit reached.")
                    self.stdout.write(f"Added {added}, updated {updated}.")
                    return
                try:
                    places, token = search_restaurants(query, token)
                except PlacesAPIError as exc:
                    self.stderr.write(self.style.ERROR(f"{query}: {exc}"))
                    break
                for place in places:
                    # The search box also covers parts of NJ and Westchester.
                    if not place.get("id") or not restaurant_fields(place)["boro"]:
                        continue
                    save_restaurant(place)
                    if place["id"] in known:
                        updated += 1
                    else:
                        known.add(place["id"])
                        added += 1
                self._pause()
                if not token:
                    break
        self.stdout.write(f"Added {added}, updated {updated}.")
