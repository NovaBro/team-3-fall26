"""Copy PlaceEnrichment and PlaceReview rows out of nyc_food.db.

Run this after `migrate --database=community` and before the search migration
that drops those tables from the default database.
"""

import json

from django.core.management.base import BaseCommand
from django.db import connections
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from community.models import PlaceEnrichment, PlaceReview


def _json(value):
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _when(value):
    if value is None or value == "":
        return None
    parsed = value if hasattr(value, "tzinfo") else parse_datetime(str(value).replace(" ", "T"))
    if parsed is not None and timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.utc)
    return parsed


class Command(BaseCommand):
    help = "Copy Google place cache from nyc_food.db into the community database."

    def handle(self, *args, **options):
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_placeenrichment'"
            )
            if cursor.fetchone() is None:
                self.stdout.write("search_placeenrichment is already gone. Nothing to copy.")
                return
            cursor.execute(
                """
                SELECT id, camis, place_id, display_name, formatted_address,
                       latitude, longitude, rating, user_rating_count, price_level,
                       price_range, website_uri, google_maps_uri, business_status,
                       raw_json, fetched_at
                FROM search_placeenrichment
                """
            )
            enrichment_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT place_id, author_name, author_uri, rating, relative_time,
                       text, publish_time, fetched_at
                FROM search_placereview
                """
            )
            review_rows = cursor.fetchall()

        id_to_camis = {row[0]: row[1] for row in enrichment_rows}
        copied = skipped = 0
        for row in enrichment_rows:
            camis = row[1]
            if PlaceEnrichment.objects.filter(camis=camis).exists():
                skipped += 1
                continue
            enrichment = PlaceEnrichment.objects.create(
                camis=camis,
                place_id=row[2] or "",
                display_name=row[3] or "",
                formatted_address=row[4] or "",
                latitude=row[5],
                longitude=row[6],
                rating=row[7],
                user_rating_count=row[8],
                price_level=row[9] or "",
                price_range=_json(row[10]),
                website_uri=row[11] or "",
                google_maps_uri=row[12] or "",
                business_status=row[13] or "",
                raw_json=_json(row[14]),
            )
            fetched_at = _when(row[15])
            if fetched_at is not None:
                PlaceEnrichment.objects.filter(pk=enrichment.pk).update(fetched_at=fetched_at)
            copied += 1

        review_copied = 0
        by_camis = {place.camis: place for place in PlaceEnrichment.objects.all()}
        for row in review_rows:
            camis = id_to_camis.get(row[0])
            place = by_camis.get(camis)
            if place is None:
                continue
            if place.reviews.filter(
                author_name=row[1] or "",
                text=row[5] or "",
                rating=row[3],
            ).exists():
                continue
            review = PlaceReview.objects.create(
                place=place,
                author_name=row[1] or "",
                author_uri=row[2] or "",
                rating=row[3],
                relative_time=row[4] or "",
                text=row[5] or "",
                publish_time=_when(row[6]),
            )
            fetched_at = _when(row[7])
            if fetched_at is not None:
                PlaceReview.objects.filter(pk=review.pk).update(fetched_at=fetched_at)
            review_copied += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Copied {copied} places ({skipped} already present) and {review_copied} reviews."
            )
        )
