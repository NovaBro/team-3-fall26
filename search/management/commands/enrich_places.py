"""Fetch Google Places data for Find food pins and store it locally.

Each place needs two API calls (Text Search + Place Details), so this command
skips pins that already have stored data unless ``--refresh`` is passed.

Usage:
    # Markets + Shop Healthy first (cheap under free caps), then restaurants:
    python manage.py enrich_places --type farmers_market --type grocery --sleep 0.5
    python manage.py enrich_places --type restaurant --limit 4000 --sleep 0.5

    python manage.py enrich_places --camis 41155161,40365429 --refresh
"""

import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from community.keys import DOHMH, FARMERS_MARKET, GROCERY, dohmh_key
from community.models import LocationLookup, PlaceEnrichment
from search.find_food import farmers_market_items, grocery_items
from search.locations import CACHE_DAYS
from search.models import RestaurantInspection
from search.services.places import PlacesAPIError, build_query, enrich_subject

TYPE_FARMERS_MARKET = "farmers_market"
TYPE_GROCERY = "grocery"
TYPE_RESTAURANT = "restaurant"
TYPE_CHOICES = (TYPE_FARMERS_MARKET, TYPE_GROCERY, TYPE_RESTAURANT)
DEFAULT_TYPES = (TYPE_FARMERS_MARKET, TYPE_GROCERY, TYPE_RESTAURANT)


class Command(BaseCommand):
    help = (
        "Query the Google Places API for farmers markets, Shop Healthy stores, "
        "and/or restaurants and store the results."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            action="append",
            choices=TYPE_CHOICES,
            dest="types",
            help=(
                "Place type to enrich (repeatable). Default: farmers_market, "
                "grocery, restaurant (in that order)."
            ),
        )
        parser.add_argument(
            "--camis",
            help="Comma-separated CAMIS ids (restaurant only; ignores --type).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of places to process (after skip filter).",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.0,
            help="Seconds to pause between places (default: 0).",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Re-fetch places that already have stored data.",
        )

    def handle(self, *args, **options):
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be a positive integer.")

        if options["camis"]:
            targets = self._restaurant_targets_by_camis(options)
            self._run_targets(targets, options)
            return

        types = options["types"] or list(DEFAULT_TYPES)
        for place_type in types:
            targets = self._targets_for_type(place_type, options)
            self.stdout.write(f"=== {place_type}: {len(targets)} to process ===")
            self._run_targets(targets, options)

    def _run_targets(self, targets, options):
        if not targets:
            self.stdout.write("Nothing to do.")
            return

        done = skipped = failed = 0
        for index, target in enumerate(targets):
            label = target["label"]
            try:
                enrichment = enrich_subject(
                    target["kind"],
                    target["key"],
                    target["query"],
                    camis=target.get("camis", ""),
                )
            except PlacesAPIError as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"{label}: {exc}"))
            else:
                done += 1
                self.stdout.write(
                    self.style.SUCCESS(f"{label}: {enrichment.display_name or 'saved'}")
                )
            if options["sleep"] and index < len(targets) - 1:
                time.sleep(options["sleep"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. enriched={done} skipped={skipped} failed={failed}"
            )
        )

    def _targets_for_type(self, place_type, options):
        if place_type == TYPE_FARMERS_MARKET:
            return self._market_targets(options)
        if place_type == TYPE_GROCERY:
            return self._grocery_targets(options)
        return self._restaurant_targets(options)

    def _existing_keys(self, kind):
        return set(
            PlaceEnrichment.objects.filter(kind=kind).values_list("key", flat=True)
        )

    def _apply_limit_and_skip(self, targets, existing_keys, options):
        refresh = options["refresh"]
        kept = []
        for target in targets:
            if target["key"] in existing_keys and not refresh:
                continue
            kept.append(target)
            if options["limit"] and len(kept) >= options["limit"]:
                break
        return kept

    def _market_targets(self, options):
        existing = self._existing_keys(FARMERS_MARKET)
        targets = [
            {
                "kind": FARMERS_MARKET,
                "key": item["key"],
                "query": item["locate_query"],
                "label": f"market:{item['name']}",
            }
            for item in farmers_market_items({})
            if item.get("locate_query")
        ]
        return self._apply_limit_and_skip(targets, existing, options)

    def _grocery_targets(self, options):
        existing = self._existing_keys(GROCERY)
        targets = [
            {
                "kind": GROCERY,
                "key": item["key"],
                "query": item["locate_query"],
                "label": f"grocery:{item['name']}",
            }
            for item in grocery_items({})
            if item.get("locate_query")
        ]
        return self._apply_limit_and_skip(targets, existing, options)

    def _restaurant_targets_by_camis(self, options):
        camis_list = [
            camis.strip() for camis in options["camis"].split(",") if camis.strip()
        ]
        existing = self._existing_keys(DOHMH)
        targets = []
        for camis in camis_list:
            key = dohmh_key(camis)
            if key in existing and not options["refresh"]:
                continue
            restaurant = (
                RestaurantInspection.objects.filter(camis=camis)
                .order_by("-inspection_date")
                .first()
            )
            if restaurant is None:
                continue
            query = build_query(restaurant)
            if not query:
                continue
            targets.append(
                {
                    "kind": DOHMH,
                    "key": key,
                    "query": query,
                    "camis": camis,
                    "label": camis,
                }
            )
            if options["limit"] and len(targets) >= options["limit"]:
                break
        return targets

    def _restaurant_targets(self, options):
        """Prefer restaurants that lack enrichment and lack stored coordinates."""
        existing = self._existing_keys(DOHMH)
        located_camis = set(
            PlaceEnrichment.objects.filter(kind=DOHMH)
            .exclude(latitude__isnull=True)
            .exclude(longitude__isnull=True)
            .values_list("camis", flat=True)
        )
        fresh_since = timezone.now() - timedelta(days=CACHE_DAYS)
        located_camis.update(
            key.split(":", 1)[1]
            for key in LocationLookup.objects.filter(
                kind=DOHMH, found=True, fetched_at__gte=fresh_since
            )
            .exclude(key="")
            .values_list("key", flat=True)
            if key.startswith("camis:")
        )

        rows = list(
            RestaurantInspection.objects.exclude(dba="")
            .order_by("camis")
            .values("camis")
            .distinct()
        )
        # Missing coords first, then the rest; within each group keep camis order.
        missing_coords = []
        has_coords = []
        for row in rows:
            camis = row["camis"]
            key = dohmh_key(camis)
            if key in existing and not options["refresh"]:
                continue
            bucket = has_coords if camis in located_camis else missing_coords
            bucket.append(camis)

        ordered = missing_coords + has_coords
        if options["limit"]:
            ordered = ordered[: options["limit"]]

        targets = []
        for camis in ordered:
            restaurant = (
                RestaurantInspection.objects.filter(camis=camis)
                .order_by("-inspection_date")
                .first()
            )
            if restaurant is None:
                continue
            query = build_query(restaurant)
            if not query:
                continue
            targets.append(
                {
                    "kind": DOHMH,
                    "key": dohmh_key(camis),
                    "query": query,
                    "camis": camis,
                    "label": camis,
                }
            )
        return targets
