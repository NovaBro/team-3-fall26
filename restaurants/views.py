import os

from urllib.parse import urlencode

from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from restaurants.forms import RestaurantFilterForm
from restaurants.inspections import attach_inspections
from restaurants.places import PlacesError, get_photo_url, get_restaurants


def search(request):
    # Any query string means the user submitted the form; an empty one is the landing page.
    form = RestaurantFilterForm(request.GET or None)
    restaurants, error = [], ""
    location = None

    if form.is_bound and form.is_valid():
        data = form.cleaned_data
        if data["lat"] is not None:
            location = {"lat": data["lat"], "lng": data["lng"]}
        try:
            restaurants = get_restaurants(
                cuisine=data["cuisine"],
                area=data["area"],
                prices=data["price"],
                diet=data["diet"],
                lat=data["lat"],
                lng=data["lng"],
                radius_m=form.radius_m,
                avoid=data["avoid"],
                open_now=data["open_now"],
                min_rating=float(data["min_rating"]) if data["min_rating"] else None,
            )
            restaurants = attach_inspections(restaurants)
        except PlacesError as exc:
            error = str(exc)

    return render(
        request,
        "restaurants/search.html",
        {
            "form": form,
            "searched": form.is_bound and form.is_valid() and not error,
            "restaurants": restaurants,
            "error": error,
            "location": location,
            "avoiding_allergens": bool(form.is_bound and form.is_valid() and form.cleaned_data["avoid"]),
            "map_points": [
                _map_point(r)
                for r in restaurants
                if r["lat"] is not None and r["lng"] is not None
            ],
            "maps_key": os.environ.get("GOOGLE_MAPS_JS_KEY", ""),
        },
    )


def _map_point(r):
    """What the pin popup shows for one restaurant (everything is optional)."""
    inspection = r.get("inspection") or {}
    photo = r.get("photo") or ""
    return {
        "name": r["name"],
        "lat": r["lat"],
        "lng": r["lng"],
        "price": r["price"],
        "address": r.get("address", ""),
        "rating": r.get("rating"),
        "rating_count": r.get("rating_count"),
        "maps_url": r.get("maps_url", ""),
        "photo_url": reverse("restaurants:photo") + "?" + urlencode({"name": photo}) if photo else "",
        "has_inspection": bool(inspection),
        "grade": inspection.get("grade", ""),
        "detail_url": reverse("search:restaurant_detail", args=[inspection["camis"]]) if inspection else "",
    }


def photo(request):
    """Redirect to a place photo; keeps the server API key out of the browser."""
    url = get_photo_url(request.GET.get("name", ""))
    if not url:
        raise Http404("No photo")
    response = redirect(url)
    response["Cache-Control"] = "public, max-age=86400"
    return response
