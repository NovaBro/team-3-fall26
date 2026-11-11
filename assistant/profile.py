"""What the assistant may know about a user.

Food preferences, health goals, allergies, a recent check-in, and the ZIP code
and borough from the home address are used. Name, contact details, street
address, photo, age, gender, height, and weight are deliberately left out
because the model doesn't need them.
"""

import re
from datetime import timedelta
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from django.utils import timezone

from accounts.models import MoodLog, UserProfile
from search.find_food import ZIP_PATTERN
from search.models import RestaurantInspection

MAX_FIELD_CHARS = 1000
NYC_TZ = ZoneInfo("America/New_York")
BOROUGHS = ("Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island")


def home_area(address):
    """Only the coarse part of a home address: {"zip": ..., "borough": ...}."""
    address = address or ""
    match = ZIP_PATTERN.search(address)
    zip_code = match.group(1) if match else ""
    borough = next(
        (
            name
            for name in BOROUGHS
            if re.search(rf"\b{name}\b", address, re.IGNORECASE)
        ),
        "",
    )
    if zip_code and not borough:
        borough = (
            RestaurantInspection.objects.filter(zipcode=zip_code)
            .exclude(boro="")
            .values_list("boro", flat=True)
            .first()
            or ""
        )
    return {"zip": zip_code, "borough": borough}


def preferences(user):
    """The saved preferences for a user."""
    profile = UserProfile.objects.filter(user=user).first()
    since = timezone.now() - timedelta(hours=24)
    mood = MoodLog.objects.filter(user=user, created_at__gte=since).first()
    return {
        "favorite_foods": profile.favorite_foods.strip() if profile else "",
        "disliked_foods": profile.disliked_foods.strip() if profile else "",
        "health_goals": profile.health_goals_display if profile else "",
        "allergies": profile.allergies.strip() if profile else "",
        "home_area": home_area(profile.home_address if profile else ""),
        "latest_check_in": (
            f"mood {mood.mood_display_label}, energy {mood.energy_display_label}"
            if mood
            else ""
        ),
    }


def has_preferences(prefs):
    return any(
        prefs[name]
        for name in ("favorite_foods", "disliked_foods", "health_goals", "allergies")
    )


def render_context(prefs, location_status=""):
    """The <user_context> block sent to the model. Never includes coordinates."""
    today = timezone.now().astimezone(NYC_TZ)
    lines = [f"today: {today:%A, %Y-%m-%d}"]
    for name in (
        "favorite_foods",
        "disliked_foods",
        "health_goals",
        "allergies",
        "latest_check_in",
    ):
        if prefs[name]:
            lines.append(f"{name}: {escape(prefs[name][:MAX_FIELD_CHARS])}")
    area = ", ".join(part for part in prefs["home_area"].values() if part)
    if area:
        lines.append(f"home_area: {escape(area)}")
    if location_status:
        lines.append(f"current_location: {location_status}")
    return "<user_context>\n" + "\n".join(lines) + "\n</user_context>"
