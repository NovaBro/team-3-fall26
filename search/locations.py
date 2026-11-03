"""Fill in coordinates for dataset rows that have none.

Farmers markets and Shop Healthy stores usually carry latitude/longitude;
DOHMH inspection records never do. For a row without coordinates we check, in
order:

1. ``PlaceEnrichment`` (restaurants enriched from the detail page), then
2. ``LocationLookup`` (earlier Google lookups, found or not), then
3. Google Places Text Search, saving the answer to ``LocationLookup``.

Step 3 only runs for the rows a visitor is looking at (one results page) or
from the ``locate_places`` command, never for a whole dataset per request.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.utils import timezone

from community.keys import DOHMH
from community.models import LocationLookup, PlaceEnrichment
from restaurants.places import PlacesError, has_api_key, locate_place

# Google's terms allow caching coordinates for at most 30 days.
CACHE_DAYS = 30
MAX_WORKERS = 5


def _fresh_since():
    return timezone.now() - timedelta(days=CACHE_DAYS)


def _camis(item):
    return item["key"].split(":", 1)[1] if item["key"].startswith("camis:") else ""


def _apply(item, lat, lng, source, address=""):
    item["lat"], item["lng"] = lat, lng
    item["location_source"] = source
    if address and not item.get("address"):
        item["address"] = address


def cached_lookups(kind, keys=None):
    """Fresh LocationLookup rows for ``kind`` as {key: row}."""
    rows = LocationLookup.objects.filter(kind=kind, fetched_at__gte=_fresh_since())
    if keys is not None:
        rows = rows.filter(key__in=list(keys))
    return {row.key: row for row in rows}


def enrichment_coordinates(camis_list=None):
    """{camis: PlaceEnrichment} for enriched restaurants that have coordinates."""
    rows = PlaceEnrichment.objects.exclude(latitude__isnull=True).exclude(
        longitude__isnull=True
    )
    if camis_list is not None:
        rows = rows.filter(camis__in=list(camis_list))
    return {row.camis: row for row in rows}


def resolve(items, fetch=True):
    """Set lat/lng in place on items that lack them.

    Each item is a dict with at least kind, key, lat, lng and ``locate_query``.
    With ``fetch=False`` only stored data is used (no Google calls).
    Returns the number of Google lookups made.
    """
    missing = [item for item in items if item.get("lat") is None and item.get("key")]
    if not missing:
        return 0

    restaurants = [item for item in missing if item["kind"] == DOHMH]
    if restaurants:
        enriched = enrichment_coordinates(_camis(item) for item in restaurants)
        for item in restaurants:
            place = enriched.get(_camis(item))
            if place:
                _apply(
                    item,
                    place.latitude,
                    place.longitude,
                    "google",
                    place.formatted_address,
                )

    still_missing = [item for item in missing if item.get("lat") is None]
    unknown = []
    for kind in {item["kind"] for item in still_missing}:
        of_kind = [item for item in still_missing if item["kind"] == kind]
        cached = cached_lookups(kind, (item["key"] for item in of_kind))
        for item in of_kind:
            row = cached.get(item["key"])
            if row is None:
                unknown.append(item)
            elif row.found:
                _apply(
                    item, row.latitude, row.longitude, "google", row.formatted_address
                )
            else:
                item["location_source"] = "not_found"

    if not fetch or not unknown or not has_api_key():
        return 0
    return _fetch(unknown)


def _lookup(item):
    try:
        return locate_place(item["locate_query"]), True
    except PlacesError:
        return None, False


def _fetch(items):
    items = [item for item in items if item.get("locate_query")]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(_lookup, items))

    # Database writes stay on this thread.
    for item, (match, answered) in zip(items, results):
        if not answered:
            continue  # Google failed; don't cache, try again next time.
        LocationLookup.objects.update_or_create(
            kind=item["kind"],
            key=item["key"],
            defaults={
                "query": item["locate_query"][:512],
                "found": match is not None,
                "place_id": (match or {}).get("id", "")[:255],
                "latitude": (match or {}).get("lat"),
                "longitude": (match or {}).get("lng"),
                "formatted_address": (match or {}).get("address", "")[:512],
            },
        )
        if match:
            _apply(item, match["lat"], match["lng"], "google", match["address"])
        else:
            item["location_source"] = "not_found"
    return len(items)
