"""Fetch Google Places data for restaurants and store it locally.

Every restaurant needs two API calls (Text Search + Place Details), so this
command skips restaurants that already have stored data unless ``--refresh`` is
passed. Use it to seed the database once, then develop against local data
without spending more credit.

Usage:
    python manage.py enrich_places --limit 25
    python manage.py enrich_places --camis 41155161,40365429 --refresh
"""

import time

from django.core.management.base import BaseCommand, CommandError

from community.models import PlaceEnrichment
from search.models import RestaurantInspection
from search.services.places import PlacesAPIError, enrich_camis


class Command(BaseCommand):
    help = "Query the Google Places API for restaurants and store the results."

    def add_arguments(self, parser):
        parser.add_argument(
            "--camis",
            help="Comma-separated CAMIS ids to enrich instead of scanning all.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of restaurants to process.",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.0,
            help="Seconds to pause between API calls (default: 0).",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            help="Re-fetch restaurants that already have stored data.",
        )

    def handle(self, *args, **options):
        camis_list = self._targets(options)
        if not camis_list:
            self.stdout.write("Nothing to do.")
            return

        existing = set(PlaceEnrichment.objects.values_list("camis", flat=True))
        done = skipped = failed = 0

        for index, camis in enumerate(camis_list):
            if camis in existing and not options["refresh"]:
                skipped += 1
                continue
            try:
                enrichment = enrich_camis(camis)
            except PlacesAPIError as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f"{camis}: {exc}"))
            else:
                done += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{camis}: {enrichment.display_name or 'saved'}"
                    )
                )
            if options["sleep"] and index < len(camis_list) - 1:
                time.sleep(options["sleep"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. enriched={done} skipped={skipped} failed={failed}"
            )
        )

    def _targets(self, options):
        if options["camis"]:
            camis_list = [
                camis.strip() for camis in options["camis"].split(",") if camis.strip()
            ]
        else:
            camis_list = list(
                RestaurantInspection.objects.order_by("camis")
                .values_list("camis", flat=True)
                .distinct()
            )
        if options["limit"]:
            if options["limit"] < 1:
                raise CommandError("--limit must be a positive integer.")
            camis_list = camis_list[: options["limit"]]
        return camis_list
