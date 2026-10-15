"""Data access for restaurants (Google Places API, Text Search "New").

Views only call get_restaurants(). To switch to another data source, replace
the body of get_restaurants() and keep the return shape the same.

Google terms restrict caching/bulk storage of Places data, so we call the
API at request time and store nothing.
"""

import math
import os

import requests

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.priceLevel",
        "places.servesVegetarianFood",
        "places.googleMapsUri",
    ]
)

# Display label <-> Google price level
PRICE_LEVELS = {
    "$": "PRICE_LEVEL_INEXPENSIVE",
    "$$": "PRICE_LEVEL_MODERATE",
    "$$$": "PRICE_LEVEL_EXPENSIVE",
    "$$$$": "PRICE_LEVEL_VERY_EXPENSIVE",
}
PRICE_LABELS = {level: label for label, level in PRICE_LEVELS.items()}

# Diet filter -> Google place type (vegetarian uses servesVegetarianFood instead)
DIET_TYPES = {
    "vegan": "vegan_restaurant",
    "halal": "halal_restaurant",
}

# Rough bounding box of the five boroughs; searches without the user's
# location are restricted to it.
NYC_BOUNDS = {
    "low": {"latitude": 40.4774, "longitude": -74.2591},
    "high": {"latitude": 40.9176, "longitude": -73.7004},
}

DEFAULT_BIAS_RADIUS_M = 2000.0
METERS_PER_MILE = 1609.344


class PlacesError(Exception):
    """Raised with a user-friendly message when the data source fails."""


def distance_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in meters (haversine)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _normalize(place):
    location = place.get("location", {})
    return {
        "id": place.get("id", ""),
        "name": place.get("displayName", {}).get("text", "(no name)"),
        "address": place.get("formattedAddress", ""),
        "price": PRICE_LABELS.get(place.get("priceLevel", ""), ""),
        "vegetarian": place.get("servesVegetarianFood"),  # True / False / None
        "lat": location.get("latitude"),
        "lng": location.get("longitude"),
        "maps_url": place.get("googleMapsUri", ""),
        "distance_mi": None,
    }


def build_request(area="", prices=(), diet="", lat=None, lng=None, radius_m=None):
    """Return the JSON body for a Text Search request."""
    area = (area or "").strip()
    if area and "new york" not in area.lower() and "nyc" not in area.lower():
        area = f"{area}, New York, NY"

    kind = f"{diet} restaurants" if diet else "restaurants"
    if area:
        query = f"{kind} in {area}"
    elif lat is not None:
        query = kind
    else:
        query = f"{kind} in New York, NY"

    body = {"textQuery": query, "maxResultCount": 20, "languageCode": "en"}
    # Google allows a circle only as a bias, so with the user's location we
    # bias toward it and enforce the distance ourselves in get_restaurants().
    if lat is not None and lng is not None:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": min(radius_m or DEFAULT_BIAS_RADIUS_M, 50000.0),
            }
        }
    else:
        body["locationRestriction"] = {"rectangle": NYC_BOUNDS}
    if prices:
        body["priceLevels"] = [PRICE_LEVELS[p] for p in prices]
    if diet in DIET_TYPES:
        body["includedType"] = DIET_TYPES[diet]
        body["strictTypeFiltering"] = True
    return body


def get_restaurants(area="", prices=(), diet="", lat=None, lng=None, radius_m=None, api_key=None):
    """Return a list of restaurant dicts matching every given filter.

    area:     free-text neighborhood/street, e.g. "East Village"
    prices:   any of "$", "$$", "$$$", "$$$$" (empty = any price)
    diet:     "", "vegetarian", "vegan" or "halal"
    lat/lng:  optional user location; results are sorted by distance
    radius_m: optional max distance from lat/lng, in meters
    """
    api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise PlacesError("GOOGLE_API_KEY is not set. Add it to your .env file.")

    body = build_request(area, prices, diet, lat, lng, radius_m)
    try:
        resp = requests.post(
            SEARCH_URL,
            json=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            timeout=10,
        )
    except requests.RequestException:
        raise PlacesError("Could not reach Google Places. Try again in a moment.")

    if resp.status_code != 200:
        raise PlacesError(
            f"Google Places returned an error ({resp.status_code}). "
            "Check the API key, billing, and that Places API (New) is enabled."
        )

    places = [_normalize(p) for p in resp.json().get("places", [])]

    # Google already applies these, but check again so the results never
    # include a restaurant that doesn't match the selected filters.
    if prices:
        places = [p for p in places if p["price"] in prices]
    if diet == "vegetarian":
        places = [p for p in places if p["vegetarian"] is True]

    if lat is not None and lng is not None:
        for p in places:
            if p["lat"] is not None and p["lng"] is not None:
                p["distance_mi"] = distance_m(lat, lng, p["lat"], p["lng"]) / METERS_PER_MILE
        if radius_m:
            limit_mi = radius_m / METERS_PER_MILE
            places = [p for p in places if p["distance_mi"] is not None and p["distance_mi"] <= limit_mi]
        places.sort(key=lambda p: (p["distance_mi"] is None, p["distance_mi"] or 0))

    return places
