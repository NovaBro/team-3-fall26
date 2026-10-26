import os

from django.shortcuts import render

from restaurants.forms import RestaurantFilterForm
from restaurants.inspections import attach_inspections
from restaurants.places import PlacesError, get_restaurants


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
                area=data["area"],
                prices=data["price"],
                diet=data["diet"],
                lat=data["lat"],
                lng=data["lng"],
                radius_m=form.radius_m,
                avoid=data["avoid"],
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
                {"name": r["name"], "lat": r["lat"], "lng": r["lng"], "price": r["price"]}
                for r in restaurants
                if r["lat"] is not None and r["lng"] is not None
            ],
            "maps_key": os.environ.get("GOOGLE_MAPS_JS_KEY", ""),
        },
    )
