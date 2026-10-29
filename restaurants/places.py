"""Data access for restaurants (Google Places API, Text Search "New").

Views only call get_restaurants(). To switch to another data source, replace
the body of get_restaurants() and keep the return shape the same.

Google terms restrict caching/bulk storage of Places data, so we call the
API at request time and store nothing.
"""

import math
import os

import requests

from restaurants.diet_filters import DIETS, risky_google_types

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
        "places.primaryType",
        "places.types",
        "places.rating",
        "places.userRatingCount",
        "places.photos",
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
        "types": {place.get("primaryType", ""), *place.get("types", [])} - {""},
        "distance_mi": None,
        "rating": place.get("rating"),
        "rating_count": place.get("userRatingCount"),
        "photo": (place.get("photos") or [{}])[0].get("name", ""),
    }


def build_request(
    area="", prices=(), diet="", lat=None, lng=None, radius_m=None,
    cuisine="",
    open_now=False, min_rating=None,
):
    """Return the JSON body for a Text Search request."""
    area = (area or "").strip()
    if area and "new york" not in area.lower() and "nyc" not in area.lower():
        area = f"{area}, New York, NY"

    google = DIETS[diet]["google"] if diet else None
    kind = google["query"] if google else "restaurants"
    cuisine = (cuisine or "").strip()
    if cuisine:
        kind = f"{cuisine} {kind}"
    if area:
        query = f"{kind} in {area}"
    elif lat is not None:
        query = kind
    else:
        query = f"{kind} in New York, NY"

    body = {"textQuery": query, "maxResultCount": 20, "languageCode": "en"}
    if open_now:
        body["openNow"] = True
    if min_rating is not None:
        body["minRating"] = float(min_rating)
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
    if google and google["type"]:
        body["includedType"] = google["type"]
        body["strictTypeFiltering"] = True
    return body


def get_restaurants(
    area="", prices=(), diet="", lat=None, lng=None, radius_m=None, avoid=(), cuisine="",
    open_now=False, min_rating=None, api_key=None,
):
    """Return a list of restaurant dicts matching every given filter.

    area:     free-text neighborhood/street, e.g. "East Village"
    prices:   any of "$", "$$", "$$$", "$$$$" (empty = any price)
    diet:     "" or a key of restaurants.diet_filters.DIETS that has a "google" entry
    lat/lng:  optional user location; results are sorted by distance
    radius_m: optional max distance from lat/lng, in meters
    avoid:    allergy keys from restaurants.diet_filters, e.g. ["nuts"]
    """
    api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise PlacesError("GOOGLE_API_KEY is not set. Add it to your .env file.")

    body = build_request(
        area, prices, diet, lat, lng, radius_m,
        cuisine=cuisine,
        open_now=open_now, min_rating=min_rating,
    )
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
    # Text Search can't exclude place types, so allergy filters run here.
    if avoid:
        risky = risky_google_types(avoid)
        places = [p for p in places if not p["types"] & risky]

    if lat is not None and lng is not None:
        for p in places:
            if p["lat"] is not None and p["lng"] is not None:
                p["distance_mi"] = distance_m(lat, lng, p["lat"], p["lng"]) / METERS_PER_MILE
        if radius_m:
            limit_mi = radius_m / METERS_PER_MILE
            places = [p for p in places if p["distance_mi"] is not None and p["distance_mi"] <= limit_mi]
        places.sort(key=lambda p: (p["distance_mi"] is None, p["distance_mi"] or 0))

    return places


# --- pin popup: one photo for a place (Google Places Photos, New) ---
import re as _re

_PHOTO_NAME = _re.compile(r"^places/[A-Za-z0-9_-]+/photos/[A-Za-z0-9_-]+$")


def get_photo_url(name, api_key=None, max_width=400):
    """Return a plain image URL for a Google photo name, or "" if unavailable.

    The API key stays on the server: Google returns a key-free image URL.
    """
    api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key or not _PHOTO_NAME.match(name or ""):
        return ""
    try:
        resp = requests.get(
            f"https://places.googleapis.com/v1/{name}/media",
            params={"maxWidthPx": max_width, "skipHttpRedirect": "true"},
            headers={"X-Goog-Api-Key": api_key},
            timeout=10,
        )
    except requests.RequestException:
        return ""
    if resp.status_code != 200:
        return ""
    return resp.json().get("photoUri", "")
