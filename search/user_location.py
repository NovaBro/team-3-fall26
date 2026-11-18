"""User pin location for distance-aware ranking (Feature 2)."""

from __future__ import annotations

from django.utils import timezone

from search.find_food import NYC_LATITUDE_RANGE, NYC_LONGITUDE_RANGE, in_nyc

DEFAULT_MAP_CENTER = (40.7128, -74.0060)  # City Hall
DEFAULT_MAP_ZOOM = 11


def parse_latlng(lat_raw, lng_raw):
    """Return (lat, lng) floats or raise ValueError."""
    try:
        lat = float(lat_raw)
        lng = float(lng_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("lat and lng must be numbers") from exc
    if not in_nyc(lat, lng):
        raise ValueError("Location must be inside New York City")
    return lat, lng


def user_latlng(user):
    """Return (lat, lng) from the user's profile pin, or None."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    from accounts.models import UserProfile

    # Query the table directly so a cleared pin is not hidden by a cached
    # ``user.profile`` related object from earlier in the request.
    row = (
        UserProfile.objects.filter(user_id=user.pk)
        .values_list("location_lat", "location_lng")
        .first()
    )
    if row is None:
        return None
    lat, lng = row
    if lat is None or lng is None:
        return None
    if not in_nyc(lat, lng):
        return None
    return float(lat), float(lng)


def save_user_latlng(user, lat, lng):
    """Persist a validated NYC pin on the user's profile. Creates profile if needed."""
    from accounts.models import UserProfile

    profile, _created = UserProfile.objects.get_or_create(user=user)
    profile.location_lat = lat
    profile.location_lng = lng
    profile.location_updated_at = timezone.now()
    profile.save(
        update_fields=["location_lat", "location_lng", "location_updated_at"]
    )
    return profile


def clear_user_latlng(user):
    """Clear the user's ranking pin."""
    from accounts.models import UserProfile

    profile, _created = UserProfile.objects.get_or_create(user=user)
    profile.location_lat = None
    profile.location_lng = None
    profile.location_updated_at = timezone.now()
    profile.save(
        update_fields=["location_lat", "location_lng", "location_updated_at"]
    )
    return profile


def map_bootstrap(user=None):
    """Dict for the home minimap: center, zoom, and optional saved pin."""
    pin = user_latlng(user) if user is not None else None
    if pin is not None:
        lat, lng = pin
        return {
            "lat": lat,
            "lng": lng,
            "zoom": 13,
            "has_pin": True,
            "nyc_lat_min": NYC_LATITUDE_RANGE[0],
            "nyc_lat_max": NYC_LATITUDE_RANGE[1],
            "nyc_lng_min": NYC_LONGITUDE_RANGE[0],
            "nyc_lng_max": NYC_LONGITUDE_RANGE[1],
        }
    lat, lng = DEFAULT_MAP_CENTER
    return {
        "lat": lat,
        "lng": lng,
        "zoom": DEFAULT_MAP_ZOOM,
        "has_pin": False,
        "nyc_lat_min": NYC_LATITUDE_RANGE[0],
        "nyc_lat_max": NYC_LATITUDE_RANGE[1],
        "nyc_lng_min": NYC_LONGITUDE_RANGE[0],
        "nyc_lng_max": NYC_LONGITUDE_RANGE[1],
    }
