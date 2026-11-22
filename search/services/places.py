"""Client for the Google Places API (New) and the stored restaurant pool.

Google Places is the only source of restaurants. Every fetched restaurant is
stored twice in community.db: a ``Restaurant`` row (the pool the site ranks)
and a ``PlaceEnrichment`` row with its reviews (kind ``restaurant_google``,
key ``google:<place_id>``). The detail page fetches a place the first time it
is opened (and on "Refresh Google data"); ``manage.py sync_restaurants`` seeds,
discovers and refreshes the pool in bulk. Other pins (farmers markets, grocery
stores) are enriched with ``enrich_subject``.

Docs: https://developers.google.com/maps/documentation/places/web-service/op-overview
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from community.keys import GOOGLE, google_key
from community.models import PlaceEnrichment, PlaceReview, Restaurant
from restaurants.boroughs import address_component, borough_for_place
from restaurants.boroughs import zip_from_address
from restaurants.cuisines import cuisine_for_types

PLACES_BASE_URL = "https://places.googleapis.com/v1"
SEARCH_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location"
)
# What a Restaurant row needs; also asked for by discovery searches.
RESTAURANT_FIELDS = (
    "id,displayName,formattedAddress,addressComponents,location,types,"
    "primaryType,rating,userRatingCount,priceLevel,businessStatus,"
    "googleMapsUri,photos"
)
DETAILS_FIELD_MASK = f"{RESTAURANT_FIELDS},priceRange,websiteUri,reviews,reviewSummary"
# Text Search can return the same fields as Place Details, so one request does
# both the lookup and the details (they are prefixed with "places.").
SEARCH_DETAILS_FIELD_MASK = ",".join(
    f"places.{field}" for field in DETAILS_FIELD_MASK.split(",")
)
DISCOVER_FIELD_MASK = (
    ",".join(f"places.{field}" for field in RESTAURANT_FIELDS.split(","))
    + ",nextPageToken"
)
REQUEST_TIMEOUT = 15
# Top picks fetch missing photos while the page renders: keep it short.
PHOTO_FIELD_MASK = "photos"
PHOTO_TIMEOUT = 3
PHOTO_RECHECK_DAYS = 30  # a place Google had no photo for is asked again after

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


def _request(method, url, field_mask, timeout=REQUEST_TIMEOUT, **kwargs):
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _api_key(),
        "X-Goog-FieldMask": field_mask,
    }
    try:
        response = requests.request(
            method, url, headers=headers, timeout=timeout, **kwargs
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


def find_place_with_details(query):
    """Top Text Search match for ``query`` with every detail field, or None.

    One request instead of ``find_place`` + ``get_place_details``.
    """
    payload = {
        "textQuery": query,
        "maxResultCount": 1,
        "locationBias": NYC_LOCATION_BIAS,
    }
    data = _request(
        "POST",
        f"{PLACES_BASE_URL}/places:searchText",
        SEARCH_DETAILS_FIELD_MASK,
        json=payload,
    )
    places = data.get("places") or []
    return places[0] if places else None


def fetch_photo_name(place_id):
    """The first Google photo reference for a place ("" when it has none).

    A Place Details request that asks for ``photos`` only, the cheapest way to
    get one. Raises PlacesAPIError (also when no API key is set).
    """
    data = _request(
        "GET",
        f"{PLACES_BASE_URL}/places/{place_id}",
        PHOTO_FIELD_MASK,
        timeout=PHOTO_TIMEOUT,
    )
    return ((data.get("photos") or [{}])[0].get("name") or "")[:512]


def _photo_or_none(place_id):
    try:
        return fetch_photo_name(place_id)
    except PlacesAPIError:
        return None  # Google down or no key: try again on a later page load


def ensure_photos(place_ids):
    """{place_id: photo reference} for these places, asking Google only when
    the stored ``photo_name`` is empty.

    Places checked within PHOTO_RECHECK_DAYS that had no photo are not asked
    again. Requests run in parallel with a short timeout; failures are left
    unrecorded so a later load retries. Google's terms allow storing the photo
    reference, not the image: the image is served by restaurants:photo.
    """
    place_ids = [place_id for place_id in dict.fromkeys(place_ids) if place_id]
    rows = list(
        Restaurant.objects.filter(place_id__in=place_ids).values_list(
            "place_id", "photo_name", "photo_checked_at"
        )
    )
    photos = {place_id: name for place_id, name, _checked in rows if name}
    cutoff = timezone.now() - timedelta(days=PHOTO_RECHECK_DAYS)
    todo = [
        place_id
        for place_id, name, checked in rows
        if not name and (checked is None or checked < cutoff)
    ]
    if not todo or not getattr(settings, "GOOGLE_PHOTO_FETCH", False):
        return photos
    if not getattr(settings, "GOOGLE_PLACES_API_KEY", ""):
        return photos
    with ThreadPoolExecutor(max_workers=len(todo)) as pool:
        results = list(zip(todo, pool.map(_photo_or_none, todo)))
    now = timezone.now()
    for place_id, name in results:
        if name is None:
            continue
        # update(), not save(): fetched_at tracks full refreshes, not photos.
        Restaurant.objects.filter(place_id=place_id).update(
            photo_name=name, photo_checked_at=now
        )
        if name:
            photos[place_id] = name
    return photos


def forget_photo(photo_name):
    """Clear a photo reference Google no longer accepts, so it is re-fetched."""
    if photo_name:
        Restaurant.objects.filter(photo_name=photo_name).update(
            photo_name="", photo_checked_at=None
        )


def get_place_details(place_id):
    """Fetch full details (rating, price, reviews, ...) for a place ID."""
    return _request("GET", f"{PLACES_BASE_URL}/places/{place_id}", DETAILS_FIELD_MASK)


def search_restaurants(query, page_token=""):
    """One page (up to 20) of NYC restaurants for ``query``.

    Returns (places, next page token or ""). Results are restricted to the
    five boroughs' bounding box and to restaurants.
    """
    payload = {
        "textQuery": query,
        "pageSize": 20,
        "languageCode": "en",
        "includedType": "restaurant",
        "locationRestriction": NYC_LOCATION_BIAS,
    }
    if page_token:
        payload["pageToken"] = page_token
    data = _request(
        "POST",
        f"{PLACES_BASE_URL}/places:searchText",
        DISCOVER_FIELD_MASK,
        json=payload,
    )
    return data.get("places") or [], data.get("nextPageToken", "")


def _localized_text(value):
    if isinstance(value, dict):
        return (value.get("text") or "").strip()
    return (value or "").strip()


def restaurant_fields(details):
    """Restaurant column values for one Google place (``id`` excluded)."""
    location = details.get("location") or {}
    components = details.get("addressComponents") or []
    address = details.get("formattedAddress", "") or ""
    zipcode = address_component(components, "postal_code") or zip_from_address(address)
    street = (
        " ".join(
            part
            for part in (
                address_component(components, "street_number"),
                address_component(components, "route"),
            )
            if part
        )
        or address.split(",", 1)[0]
    )
    return {
        "name": _localized_text(details.get("displayName"))[:255],
        "address": address[:512],
        "street": street[:255],
        "zipcode": zipcode[:10],
        "boro": borough_for_place(components, zipcode),
        "cuisine": cuisine_for_types(
            details.get("primaryType", ""), details.get("types") or ()
        ),
        "primary_type": (details.get("primaryType") or "")[:64],
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "rating": details.get("rating"),
        "rating_count": details.get("userRatingCount"),
        "price_level": details.get("priceLevel", "") or "",
        "business_status": details.get("businessStatus", "") or "",
        "maps_url": details.get("googleMapsUri", "") or "",
        "photo_name": ((details.get("photos") or [{}])[0].get("name") or "")[:512],
    }


def save_restaurant(details):
    """Create or update the Restaurant row for a Google place; returns it.

    Blank values never overwrite stored ones, so a place whose types are all
    generic keeps the cuisine it already had.
    """
    place_id = details.get("id", "")
    if not place_id:
        raise PlacesAPIError("Google returned a place without an id.")
    fields = restaurant_fields(details)
    restaurant = Restaurant.objects.filter(place_id=place_id).first()
    if restaurant is None:
        restaurant = Restaurant(place_id=place_id)
    for name, value in fields.items():
        if value not in ("", None) or getattr(restaurant, name) in ("", None):
            setattr(restaurant, name, value)
    restaurant.save()
    return restaurant


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


def _save(kind, key, details):
    location = details.get("location") or {}
    enrichment, _created = PlaceEnrichment.objects.update_or_create(
        kind=kind,
        key=key,
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
    if kind == GOOGLE:
        save_restaurant(details)
    return enrichment


@transaction.atomic(using="community")
def enrich_subject(kind, key, query):
    """Look up any Find food pin on Google and persist its data.

    Overwrites any previously stored data for this (kind, key). Raises
    ``PlacesAPIError`` on any failure.
    """
    if not query:
        raise PlacesAPIError("No name or address to search with.")

    details = find_place_with_details(query)
    if not details or not details.get("id"):
        raise PlacesAPIError(f"No Google place matched {query!r}.")
    return _save(kind, key, details)


@transaction.atomic(using="community")
def enrich_place_id(place_id):
    """Fetch one restaurant from Google by place id and store it.

    Writes its Restaurant row, PlaceEnrichment and reviews. Raises
    ``PlacesAPIError`` on any failure.
    """
    if not place_id:
        raise PlacesAPIError("No place id given.")
    details = get_place_details(place_id)
    if not details or not details.get("id"):
        raise PlacesAPIError(f"Google has no place {place_id!r}.")
    return _save(GOOGLE, google_key(details["id"]), details)
