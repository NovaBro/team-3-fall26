"""Rebuild RestaurantSummary from the inspection rows (after a bulk import).

python manage.py rebuild_restaurant_summary
"""

import time

from django.core.management.base import BaseCommand

from search.models import RestaurantInspection, RestaurantSummary
from search.summary import rebuild_all


class Command(BaseCommand):
    help = "Rebuild the one-row-per-restaurant summary used by Top picks."

    def handle(self, *args, **options):
        start = time.perf_counter()
        total = rebuild_all(RestaurantInspection, RestaurantSummary)
        seconds = time.perf_counter() - start
        self.stdout.write(f"{total} restaurants summarised in {seconds:.1f} s")
