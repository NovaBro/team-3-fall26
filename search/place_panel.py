"""Left-side place panel on the Search page, built from our own data.

One HTML fragment per place (search/panel/?key=...), the same for a list click
and a map dot click. Restaurants get photo, rating, health score, why it's
healthy, what to order and links; markets and groceries get the basics.
"""

from urllib.parse import quote_plus

from community.keys import GOOGLE
from community.models import (
    HealthScore,
    PlaceEnrichment,
    PlaceReview,
    ReasonBlurb,
    Restaurant,
)
from search.find_food import _photo_url
from search.menustat import top_low_calorie_meals
from search.profile_options import GOAL_LABELS

KIND_LABELS = {
    "restaurant_google": "Restaurant",
    "restaurant": "Restaurant",
    "farmers_market": "Farmers market",
    "grocery": "Grocery",
}


def _money(part):
    try:
        return int(float((part or {}).get("units")))
    except (TypeError, ValueError):
        return None


def _price_range(raw):
    if not isinstance(raw, dict):
        return ""
    low, high = _money(raw.get("startPrice")), _money(raw.get("endPrice"))
    if low is not None and high is not None:
        return f"${low}–{high} per person"
    if low is not None:
        return f"${low}+ per person"
    return ""


def _directions(lat, lng, address):
    if lat is not None and lng is not None:
        return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}"
    if address:
        return "https://www.google.com/maps/dir/?api=1&destination=" + quote_plus(
            address
        )
    return ""


def _stars(rating):
    full = int(round(rating or 0))
    return "★" * full + "☆" * (5 - full)


def panel_context(key, name="", address="", category="", lat=None, lng=None):
    ctx = {
        "name": name,
        "address": address,
        "kind_label": KIND_LABELS.get(category, ""),
        "is_restaurant": False,
        "directions": _directions(lat, lng, address),
    }
    if not key.startswith("google:"):
        return ctx
    place_id = key[len("google:") :]  # noqa: E203
    row = Restaurant.objects.filter(place_id=place_id).first()
    place = PlaceEnrichment.objects.filter(kind=GOOGLE, place_id=place_id).first()
    if row is None and place is None:
        return ctx

    name = (row and row.name) or (place and place.display_name) or name
    address = (row and row.address) or (place and place.formatted_address) or address
    rating = (place and place.rating) or (row and row.rating)
    count = (place and place.user_rating_count) or (row and row.rating_count)
    lat = (row and row.latitude) or lat
    lng = (row and row.longitude) or lng

    health = HealthScore.objects.filter(place_id=place_id).first()
    goals = []
    if health and health.goal_scores:
        best = sorted(health.goal_scores.items(), key=lambda kv: -kv[1])[:2]
        goals = [
            (GOAL_LABELS.get(k, k.replace("-", " ").capitalize()), round(v * 100))
            for k, v in best
        ]
    blurb = (
        ReasonBlurb.objects.filter(place_id=place_id)
        .values_list("text", flat=True)
        .first()
    )

    meals, _chain = top_low_calorie_meals(name, limit=3) if name else ([], None)
    dishes = [
        {
            "name": m.item_name,
            "calories": round(m.calories) if m.calories is not None else None,
            "protein": (
                round(m.protein) if getattr(m, "protein", None) is not None else None
            ),
        }
        for m in meals
    ]

    menu_note = "From the chain's published menu" if dishes else ""
    if not dishes:
        from search.menu_estimate import estimated_items

        mains = [i for i in estimated_items(place_id) if i.get("kind") == "main"]
        mains.sort(key=lambda i: (i.get("calories") is None, i.get("calories") or 0))
        dishes = [
            {
                "name": i["name"],
                "calories": i.get("calories"),
                "protein": None,
                "note": i.get("description", ""),
            }
            for i in mains[:3]
        ]
        menu_note = "Estimated from the restaurant's menu" if dishes else ""
    reviews = []
    if place is not None:
        reviews = list(
            PlaceReview.objects.filter(place=place)
            .exclude(text="")
            .order_by("-publish_time")[:3]
        )

    ctx.update(
        name=name,
        address=address,
        kind_label=(row and row.cuisine) or "Restaurant",
        boro=(row and row.boro) or "",
        is_restaurant=True,
        photo=_photo_url(row and row.photo_name),
        rating=rating,
        stars=_stars(rating) if rating else "",
        rating_count=count,
        price=(row and row.price) or "",
        price_range=_price_range(place and place.price_range),
        health=round(health.score * 100) if health else None,
        goals=goals,
        blurb=blurb or "",
        dishes=dishes,
        menu_note=menu_note,
        reviews=reviews,
        website=(place and place.website_uri) or "",
        maps=(place and place.google_maps_uri) or (row and row.maps_url) or "",
        directions=_directions(lat, lng, address),
        detail_url=f"/restaurant/{place_id}/",
    )
    return ctx
