"""Fetch Google Places data for farmers markets and Shop Healthy stores.

Each place is one Text Search request, so this command skips pins that
already have stored data unless ``--refresh`` is passed. Restaurants come from
Google directly; use ``manage.py sync_restaurants`` for them.

Usage:
    python manage.py enrich_places --type farmers_market --type grocery --sleep 0.5
"""

import time

from django.core.management.base import BaseCommand, CommandError

from community.keys import FARMERS_MARKET, GROCERY
from community.models import PlaceEnrichment
from search.find_food import farmers_market_items, grocery_items
from search.services.places import PlacesAPIError, enrich_subject

TYPE_FARMERS_MARKET = "farmers_market"
TYPE_GROCERY = "grocery"
TYPE_CHOICES = (TYPE_FARMERS_MARKET, TYPE_GROCERY)
DEFAULT_TYPES = (TYPE_FARMERS_MARKET, TYPE_GROCERY)


class Command(BaseCommand):
    help = (
        "Query the Google Places API for farmers markets and Shop Healthy "
        "stores and store the results."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            action="append",
            choices=TYPE_CHOICES,
            dest="types",
            help=(
                "Place type to enrich (repeatable). Default: farmers_market, "
                "grocery."
            ),
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
                    target["kind"], target["key"], target["query"]
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
        return self._grocery_targets(options)

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
