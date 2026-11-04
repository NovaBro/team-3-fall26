"""Look up coordinates on Google for dataset rows that have none.

Usage:
    python manage.py locate_places                 # markets + grocery stores
    python manage.py locate_places --type restaurant --limit 200

Results are saved to ``LocationLookup`` (found or not), so the Find food map
shows these places without asking Google on page load. Each lookup is one
Text Search request. Rows already looked up in the last 30 days are skipped.
Needs GOOGLE_API_KEY.
"""

from django.core.management.base import BaseCommand, CommandError

from restaurants.places import has_api_key
from search import find_food
from search.forms import FARMERS_MARKET, GROCERY, RESTAURANT
from search.locations import resolve

BATCH = 25


class Command(BaseCommand):
    help = "Find Google coordinates for farmers markets, stores and restaurants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            action="append",
            choices=[FARMERS_MARKET, GROCERY, RESTAURANT],
            help="Store type to locate (repeatable). Default: markets and grocery.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum Google lookups to make (default 100).",
        )

    def handle(self, *args, **options):
        if not has_api_key():
            raise CommandError("GOOGLE_API_KEY is not set.")
        types = options["type"] or [FARMERS_MARKET, GROCERY]
        budget = options["limit"]
        for store_type in types:
            looked_up = 0
            for batch in self._batches(store_type):
                if budget <= 0:
                    break
                unlocated = [item for item in batch if item["lat"] is None][:budget]
                made = resolve(unlocated, fetch=True)
                budget -= made
                looked_up += made
            self.stdout.write(
                self.style.SUCCESS(f"{store_type}: {looked_up} Google lookups")
            )

    def _batches(self, store_type):
        if store_type == RESTAURANT:
            rows = find_food.restaurant_rows({})
            for start in range(0, rows.count(), BATCH * 4):
                items = [
                    find_food.restaurant_item(row)
                    for row in rows[start : start + BATCH * 4]  # noqa: E203
                ]
                resolve(items, fetch=False)
                yield items
            return
        builder = (
            find_food.farmers_market_items
            if store_type == FARMERS_MARKET
            else find_food.grocery_items
        )
        items = builder({})
        resolve(items, fetch=False)
        for start in range(0, len(items), BATCH):
            yield items[start : start + BATCH]  # noqa: E203
