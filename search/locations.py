"""Fill in coordinates for dataset rows that have none.

Farmers markets and Shop Healthy stores usually carry latitude/longitude, and
restaurants (from Google) always do. For a row without coordinates we check,
in order:

1. ``LocationLookup`` (earlier Google lookups, found or not), then
2. Google Places Text Search, saving the answer to ``LocationLookup``.

Step 2 only runs for the rows a visitor is looking at (one results page) or
from the ``locate_places`` command, never for a whole dataset per request.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.utils import timezone

from community.models import LocationLookup
from restaurants.places import PlacesError, has_api_key, locate_place

# Google's terms allow caching coordinates for at most 30 days.
CACHE_DAYS = 30
MAX_WORKERS = 5


def _fresh_since():
    return timezone.now() - timedelta(days=CACHE_DAYS)


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


def resolve(items, fetch=True):
    """Set lat/lng in place on items that lack them.

    Each item is a dict with at least kind, key, lat, lng and ``locate_query``.
    With ``fetch=False`` only stored data is used (no Google calls).
    Returns the number of Google lookups made.
    """
    missing = [item for item in items if item.get("lat") is None and item.get("key")]
    if not missing:
        return 0

    unknown = []
    for kind in {item["kind"] for item in missing}:
        of_kind = [item for item in missing if item["kind"] == kind]
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
