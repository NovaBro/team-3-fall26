"""Client for the Google Places API (New).

The web UI only calls into this module when the user clicks "Get Google data"
on a restaurant page; the ``enrich_places`` management command reuses it for
bulk seeding. Results are persisted so repeat views never hit the API.

Docs: https://developers.google.com/maps/documentation/places/web-service/op-overview
"""

import requests
from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime

from community.models import PlaceEnrichment, PlaceReview
from search.models import RestaurantInspection

PLACES_BASE_URL = "https://places.googleapis.com/v1"
SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location"
)
DETAILS_FIELD_MASK = (
    "id,displayName,formattedAddress,location,rating,userRatingCount,"
    "priceLevel,priceRange,websiteUri,googleMapsUri,businessStatus,reviews"
)
REQUEST_TIMEOUT = 15

# Bias text searches toward the five boroughs so "Joe's Pizza" resolves locally.
NYC_LOCATION_BIAS = {
    "rectangle": {
        "low": {"latitude": 40.477, "longitude": -74.259},
        "high": {"latitude": 40.917, "longitude": -73.700},
    }
}


class PlacesAPIError(Exception):
    """Raised when the Places API cannot be queried or fails."""


def _api_key():
    key = getattr(settings, "GOOGLE_PLACES_API_KEY", "")
    if not key:
        raise PlacesAPIError(
            "GOOGLE_PLACES_API_KEY is not set. Export it before enriching."
        )
    return key


def _request(method, url, field_mask, **kwargs):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _api_key(),
        "X-Goog-FieldMask": field_mask,
    }
    try:
        response = requests.request(
            method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs
        )
    except requests.RequestException as exc:
        raise PlacesAPIError(f"Could not reach the Places API: {exc}") from exc

    if response.status_code != 200:
        message = response.text[:500]
        try:
            message = response.json().get("error", {}).get("message", message)
        except ValueError:
            pass
        raise PlacesAPIError(f"Places API error ({response.status_code}): {message}")
    return response.json()


def find_place(query):
    """Return the top Text Search match for ``query`` or None."""
    payload = {
        "textQuery": query,
        "maxResultCount": 1,
        "locationBias": NYC_LOCATION_BIAS,
    }
    data = _request(
        "POST", f"{PLACES_BASE_URL}/places:searchText", SEARCH_FIELD_MASK, json=payload
    )
    places = data.get("places") or []
    return places[0] if places else None


def get_place_details(place_id):
    """Fetch full details (rating, price, reviews, ...) for a place ID."""
    return _request("GET", f"{PLACES_BASE_URL}/places/{place_id}", DETAILS_FIELD_MASK)


def build_query(restaurant):
    """Turn a DOHMH inspection row into a human address query."""
    parts = [
        restaurant.dba,
        restaurant.street,
        restaurant.boro,
        "NY",
        restaurant.zipcode,
    ]
    return " ".join(part for part in parts if part).strip()


def _localized_text(value):
    if isinstance(value, dict):
        return (value.get("text") or "").strip()
    return (value or "").strip()


def _build_review(place, review):
    author = review.get("authorAttribution") or {}
    return PlaceReview(
        place=place,
        author_name=_localized_text(author.get("displayName"))[:255],
        author_uri=author.get("uri", "") or "",
        rating=review.get("rating"),
        relative_time=review.get("relativePublishTimeDescription", "") or "",
        text=_localized_text(review.get("text")),
        publish_time=parse_datetime(review.get("publishTime", "") or ""),
    )


def _save(camis, details):
    location = details.get("location") or {}
    enrichment, _created = PlaceEnrichment.objects.update_or_create(
        camis=camis,
        defaults={
            "place_id": details.get("id", "") or "",
            "display_name": _localized_text(details.get("displayName"))[:255],
            "formatted_address": details.get("formattedAddress", "") or "",
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "rating": details.get("rating"),
            "user_rating_count": details.get("userRatingCount"),
            "price_level": details.get("priceLevel", "") or "",
            "price_range": details.get("priceRange"),
            "website_uri": details.get("websiteUri", "") or "",
            "google_maps_uri": details.get("googleMapsUri", "") or "",
            "business_status": details.get("businessStatus", "") or "",
            "raw_json": details,
        },
    )

    enrichment.reviews.all().delete()
    reviews = details.get("reviews") or []
    if reviews:
        PlaceReview.objects.bulk_create(
            [_build_review(enrichment, review) for review in reviews]
        )
    return enrichment


@transaction.atomic(using="community")
def enrich_camis(camis):
    """Look up a restaurant on Google and persist its data.

    Overwrites any previously stored data for this CAMIS. Raises
    ``PlacesAPIError`` on any failure.
    """
    restaurant = (
        RestaurantInspection.objects.filter(camis=camis)
        .order_by("-inspection_date")
        .first()
    )
    if restaurant is None:
        raise PlacesAPIError(f"No restaurant found for CAMIS {camis}.")

    query = build_query(restaurant)
    if not query:
        raise PlacesAPIError("Restaurant has no name or address to search with.")

    match = find_place(query)
    if not match or not match.get("id"):
        raise PlacesAPIError(f"No Google place matched {query!r}.")

    details = get_place_details(match["id"])
    return _save(camis, details)
