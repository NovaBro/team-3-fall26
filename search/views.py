from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Max
from django.http import Http404, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from assistant.recommend import personalized_picks
from community.models import PlaceEnrichment, PlaceReview
from restaurants.diet_filters import ALLERGY_CHOICES
from restaurants.inspections import _latest, _match, _restaurants_in_zip, google_zip
from restaurants.places import PlacesError, find_restaurant_place
from search import find_food
from search.forms import (
    FARMERS_MARKET,
    GOOGLE,
    GROCERY,
    INSPECTIONS,
    RESTAURANT,
    STORE_TYPE_CHOICES,
    FindFoodForm,
)
from search.locations import resolve
from search.models import RestaurantInspection
from search.services.places import PlacesAPIError, enrich_camis

PAGE_SIZE = 25


def index(request):
    """Find food: farmers markets, grocery stores and restaurants on one map."""
    data = request.GET.copy()
    if not data.getlist("types"):
        data.setlist("types", [value for value, _label in STORE_TYPE_CHOICES])
    if not data.get("source"):
        data["source"] = INSPECTIONS
    form = FindFoodForm(data)
    context = {
        "form": form,
        "page_obj": None,
        "items": [],
        "map_points": [],
        "result_points": [],
        "counts": {},
        "login_url": reverse("accounts:login"),
        "error": "",
        "notes": [],
        "location": None,
        "store_types": STORE_TYPE_CHOICES,
    }
    if form.is_valid():
        context.update(_find_food(form))
    return render(request, "search/index.html", context)


def _find_food(form):
    data = form.cleaned_data
    lat, lng, radius_m = data["lat"], data["lng"], form.radius_m
    types = data["types"]
    google = data["source"] == GOOGLE
    notes, error = [], ""

    markets = find_food.farmers_market_items(data) if FARMERS_MARKET in types else []
    stores = find_food.grocery_items(data) if GROCERY in types else []
    # Stored coordinates only here; Google is asked for the visible page below.
    resolve(markets + stores, fetch=False)
    markets = find_food.near(markets, lat, lng, radius_m)
    stores = find_food.near(stores, lat, lng, radius_m)

    restaurants, rows = [], None
    if RESTAURANT in types:
        if google:
            try:
                restaurants = find_food.google_restaurant_items(data, radius_m)
            except PlacesError as exc:
                error = str(exc)
        else:
            rows = find_food.restaurant_rows(data)
            if radius_m:
                notes.append(
                    "Distance only narrows farmers markets and grocery stores. "
                    "Choose Google Places to find restaurants near you."
                )
    if form.google_only_filters_ignored:
        notes.append(
            "Price, rating and open-now filters only apply to Google Places results."
        )

    if rows is not None:
        chain = find_food.Chain(
            (rows, find_food.restaurant_item),
            (markets, _same),
            (stores, _same),
        )
    else:
        chain = find_food.Chain((restaurants, _same), (markets, _same), (stores, _same))
    page_obj = Paginator(chain, PAGE_SIZE).get_page(form.data.get("page"))
    items = list(page_obj.object_list)
    find_food.fill_latest_grades(items)
    resolve(items, fetch=True)
    find_food.set_distances(items, lat, lng)

    on_map = {}
    restaurants_on_map = (
        find_food.located_restaurant_items(rows) if rows is not None else restaurants
    )
    for item in [*items, *restaurants_on_map, *markets, *stores]:
        if item["lat"] is not None:
            on_map.setdefault(item["key"], find_food.map_point(item))

    restaurant_count = chain.lengths()[0]
    return {
        "page_obj": page_obj,
        "items": items,
        "map_points": list(on_map.values()),
        "result_points": [find_food.map_point(item) for item in items],
        "counts": {
            RESTAURANT: restaurant_count if RESTAURANT in types else None,
            FARMERS_MARKET: len(markets) if FARMERS_MARKET in types else None,
            GROCERY: len(stores) if GROCERY in types else None,
        },
        "total": page_obj.paginator.count,
        "error": error,
        "notes": notes,
        "location": {"lat": lat, "lng": lng} if lat is not None else None,
        "avoiding_allergens": bool(data["avoid"]) and RESTAURANT in types,
        "allergy_options": ALLERGY_CHOICES,
    }


def _same(item):
    return item


def _redirect_to_index(request, **defaults):
    """Old tabs now live on the Find food page; keep their links working."""
    query = request.GET.copy() if request.GET else QueryDict(mutable=True)
    for name, value in defaults.items():
        if name not in query:
            query.setlist(name, value if isinstance(value, list) else [value])
    url = reverse("search:index")
    return redirect(f"{url}?{query.urlencode()}" if query else url, permanent=False)


def find_restaurants_redirect(request):
    # A submitted Find restaurants search was a live Google search.
    defaults = {"types": [RESTAURANT], "source": GOOGLE} if request.GET else {}
    return _redirect_to_index(request, **defaults)


def farmers_markets_redirect(request):
    return _redirect_to_index(request, types=[FARMERS_MARKET])


def combined_map_redirect(request):
    return _redirect_to_index(request)


def explore_redirect(request, slug=""):
    return _redirect_to_index(request)


def _photo_url_for(google_place):
    photo = (google_place or {}).get("photo")
    if photo:
        return reverse("restaurants:photo") + "?" + urlencode({"name": photo})
    return ""


def _pick_rows(queryset):
    return (
        queryset.exclude(dba="")
        .values("camis")
        .annotate(
            name=Max("dba"),
            boro=Max("boro"),
            street=Max("street"),
            zipcode=Max("zipcode"),
            cuisine=Max("cuisine"),
            last_date=Max("inspection_date"),
        )
    )


def _top_picks(count=3, user=None):
    """Return *count* restaurants enriched with Google Places data and DOHMH
    inspection details.  Each entry is a dict with keys: name, cuisine, street,
    boro, zipcode, google (Places dict or None), inspection (dict with
    camis/grade/date or None), and reason (why Claude chose it, or "").

    Logged-in users with a profile get Claude's ranking when it's available;
    everyone else gets the most recently inspected grade-A restaurants."""

    # 1. Pick the restaurants.
    personalized = personalized_picks(user, count) if user else []
    if personalized:
        reasons = {pick["camis"]: pick["reason"] for pick in personalized}
        rows = _pick_rows(RestaurantInspection.objects.filter(camis__in=list(reasons)))
        order = list(reasons)
        picks = sorted(rows, key=lambda row: order.index(row["camis"]))
        for pick in picks:
            pick["reason"] = reasons[pick["camis"]]
    else:
        rows = _pick_rows(RestaurantInspection.objects.filter(grade="A"))
        picks = list(rows.order_by("-last_date")[:count])

    # 2. Enrich each pick with Google Places data (concurrent).
    with ThreadPoolExecutor(max_workers=count) as executor:
        lookups = [
            executor.submit(
                find_restaurant_place,
                pick["name"],
                pick["zipcode"],
                pick["street"],
            )
            for pick in picks
        ]
        for pick, lookup in zip(picks, lookups):
            pick["google"] = lookup.result()
            pick["photo_url"] = _photo_url_for(pick["google"])

    # 3. Match each pick to its DOHMH inspection via _match() / _latest().
    for pick in picks:
        google = pick["google"]
        if google and google.get("address"):
            zipcode = google_zip(google["address"])
            if zipcode:
                camis = _match(
                    google["name"],
                    google["address"],
                    _restaurants_in_zip(zipcode),
                )
                pick["inspection"] = _latest(camis) if camis else None
            else:
                pick["inspection"] = _latest(pick["camis"])
        else:
            # Fallback: use the camis we already know from the DB row.
            pick["inspection"] = _latest(pick["camis"])
        pick["image"] = "search/images/nyc-restaurant.jpg"

        # Choose one comment from Google API
        # (fallback to saved PlaceReview if available).
        chosen_review = (google or {}).get("review")
        if not chosen_review:
            camis_id = (pick.get("inspection") or {}).get("camis") or pick.get("camis")
            if camis_id:
                db_review = (
                    PlaceReview.objects.filter(place__camis=camis_id)
                    .exclude(text="")
                    .order_by("-id")
                    .first()
                )
                if db_review:
                    chosen_review = {
                        "text": db_review.text,
                        "author_name": db_review.author_name,
                        "rating": db_review.rating,
                        "relative_time": db_review.relative_time,
                    }
        pick["review"] = chosen_review

    return picks


def home(request):
    selected_boro = request.GET.get("boro", "").strip()
    borough_options = list(
        RestaurantInspection.objects.exclude(boro="")
        .exclude(boro__isnull=True)
        .values_list("boro", flat=True)
        .distinct()
        .order_by("boro")
    )
    restaurant_rows = (
        RestaurantInspection.objects.exclude(dba="")
        .values("camis")
        .annotate(
            name=Max("dba"),
            boro=Max("boro"),
            street=Max("street"),
            zipcode=Max("zipcode"),
            cuisine=Max("cuisine"),
        )
        .order_by("name", "camis")
    )
    if selected_boro in borough_options:
        restaurant_rows = restaurant_rows.filter(boro__iexact=selected_boro)
    else:
        selected_boro = ""
    page_obj = Paginator(restaurant_rows, 16).get_page(request.GET.get("page"))
    restaurants = list(page_obj.object_list)
    for row in restaurants:
        row["image"] = "search/images/nyc-restaurant.jpg"

    # Place searches supplement the CSV fields that are absent, such as a full
    # street address, price level, and Google Maps link. Failed searches leave
    # the underlying CSV card intact.
    with ThreadPoolExecutor(max_workers=4) as executor:
        lookups = [
            executor.submit(
                find_restaurant_place,
                row["name"],
                row["zipcode"],
                row["street"],
            )
            for row in restaurants
        ]
        for row, lookup in zip(restaurants, lookups):
            row["google"] = lookup.result()
            row["photo_url"] = _photo_url_for(row["google"])

    # Top 3 picks – only fetch on the first page (no borough filter) so we
    # don't slow down paginated browsing.
    top_picks = []
    if not selected_boro and page_obj.number == 1:
        top_picks = _top_picks(count=3, user=request.user)

    return render(
        request,
        "search/home.html",
        {
            "restaurants": restaurants,
            "page_obj": page_obj,
            "borough_options": borough_options,
            "selected_boro": selected_boro,
            "top_picks": top_picks,
            "personalized_picks": any(pick.get("reason") for pick in top_picks),
        },
    )


def restaurant_detail(request, camis):
    inspections = RestaurantInspection.objects.filter(camis=camis).order_by(
        "-inspection_date"
    )
    latest = inspections.first()
    if latest is None:
        raise Http404("Restaurant not found")
    place = (
        PlaceEnrichment.objects.filter(camis=camis).prefetch_related("reviews").first()
    )
    return render(
        request,
        "search/restaurant_detail.html",
        {
            "camis": camis,
            "dba": latest.dba,
            "boro": latest.boro,
            "street": latest.street,
            "zipcode": latest.zipcode,
            "cuisine": latest.cuisine,
            "inspections": inspections,
            "place": place,
        },
    )


@require_POST
def refresh_place(request, camis):
    try:
        enrich_camis(camis)
    except PlacesAPIError as exc:
        messages.error(request, f"Could not fetch Google data: {exc}")
    else:
        messages.success(request, "Google data updated.")
    return redirect("search:restaurant_detail", camis=camis)
