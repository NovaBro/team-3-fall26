import os
import re
from concurrent.futures import ThreadPoolExecutor

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Max, Q, Subquery, OuterRef
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from restaurants.diet_filters import (
    ALLERGIES,
    ALLERGY_CHOICES,
    DIETS,
    HOMEPAGE_DIET_CHOICES,
    risky_cuisines,
)
from restaurants.forms import AREA_CHOICES, DIET_CHOICES, PRICE_CHOICES, RestaurantFilterForm
from restaurants.places import PlacesError, find_restaurant_place, get_restaurants
from search.models import FarmersMarket, HealthyStore, PlaceEnrichment, RestaurantInspection
from search.registry import DATASETS
from search.services.places import PlacesAPIError, enrich_camis

PAGE_SIZE = 25
NYC_LATITUDE_RANGE = (40.3, 41.1)
NYC_LONGITUDE_RANGE = (-74.3, -73.6)
FARMERS_MARKET_LOCATION_OVERRIDES = {
    "Saratoga Farm Stand": {
        "street_address": "1965 Fulton St, Brooklyn, NY 11233",
        "zip_code": "11233",
        "latitude": 40.6785,
        "longitude": -73.916194,
    },
}

BOROUGHS = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"]
GRADES = ["A", "B", "C", "N", "P", "Z"]
MARKET_DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
MARKET_DAY_PATTERN = re.compile(
    r"\b(Mondays?|Mon|Tuesdays?|Tues?|Wednesdays?|Weds?|"
    r"Thursdays?|Thurs?|Thurs?|Fridays?|Fris?|Saturdays?|Sats?|Sundays?|Suns?)\b",
    re.IGNORECASE,
)

def _market_operates_on_day(days_of_operation, selected_day):
    matches = list(MARKET_DAY_PATTERN.finditer(days_of_operation or ""))
    found_days = set()
    for index, match in enumerate(matches):
        day_index = next(
            (
                number
                for number, day in enumerate(MARKET_DAYS)
                if day.casefold().startswith(match.group().casefold()[:3])
            ),
            None,
        )
        if day_index is None:
            continue
        found_days.add(day_index)
        if index + 1 < len(matches):
            between = days_of_operation[match.end() : matches[index + 1].start()]
            if re.fullmatch(r"\s*[-–]\s*", between):
                next_day = next(
                    (
                        number
                        for number, day in enumerate(MARKET_DAYS)
                        if day.casefold().startswith(
                            matches[index + 1].group().casefold()[:3]
                        )
                    ),
                    None,
                )
                if next_day is not None:
                    current = day_index
                    while current != next_day:
                        current = (current + 1) % len(MARKET_DAYS)
                        found_days.add(current)
    return selected_day in MARKET_DAYS and MARKET_DAYS.index(selected_day) in found_days


def _filter_restaurants(qs, name, boro, zipcode, grade, diet="", avoid=()):
    if name:
        qs = qs.filter(dba__icontains=name)
    if boro:
        qs = qs.filter(boro=boro)
    if zipcode:
        qs = qs.filter(zipcode__startswith=zipcode)
    if grade:
        qs = qs.filter(grade=grade)
    if diet:
        qs = qs.filter(cuisine__in=DIETS[diet]["cuisines"])
    if avoid:
        qs = qs.exclude(cuisine__in=risky_cuisines(avoid))
    return qs


def index(request):
    name = request.GET.get("q", "").strip()
    boro = request.GET.get("boro", "").strip()
    zipcode = request.GET.get("zip", "").strip()
    grade = request.GET.get("grade", "").strip()
    diet = request.GET.get("diet", "").strip()
    if diet not in dict(HOMEPAGE_DIET_CHOICES):
        diet = ""
    avoid = [a for a in request.GET.getlist("avoid") if a in ALLERGIES]

    page_obj = None
    if name or boro or zipcode or grade or diet or avoid:
        base = _filter_restaurants(
            RestaurantInspection.objects.all(), name, boro, zipcode, grade, diet, avoid
        )
        latest = RestaurantInspection.objects.filter(
            camis=OuterRef("camis")
        ).order_by("-inspection_date")
        restaurants = (
            base.values("camis")
            .annotate(
                name=Max("dba"),
                boro=Max("boro"),
                street=Max("street"),
                zipcode=Max("zipcode"),
                cuisine=Max("cuisine"),
                last_date=Max("inspection_date"),
                grade=Subquery(latest.values("grade")[:1]),
            )
            .order_by("name")
        )
        page_obj = Paginator(restaurants, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(
        request,
        "search/index.html",
        {
            "name": name,
            "boro": boro,
            "zip": zipcode,
            "grade": grade,
            "diet": diet,
            "avoid": avoid,
            "page_obj": page_obj,
            "boro_options": BOROUGHS,
            "grade_options": GRADES,
            "diet_options": HOMEPAGE_DIET_CHOICES,
            "allergy_options": ALLERGY_CHOICES,
            "searched": bool(page_obj),
        },
    )


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

    return render(
        request,
        "search/home.html",
        {
            "restaurants": restaurants,
            "page_obj": page_obj,
            "borough_options": borough_options,
            "selected_boro": selected_boro,
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
        PlaceEnrichment.objects.filter(camis=camis)
        .prefetch_related("reviews")
        .first()
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


def explore_index(request):
    return render(request, "search/explore_index.html", {"datasets": DATASETS})


def farmers_markets_map(request):
    latest_year = FarmersMarket.objects.aggregate(latest_year=Max("year"))[
        "latest_year"
    ]
    markets = []
    name = request.GET.get("q", "").strip()
    zipcode = request.GET.get("zip", "").strip()
    day = request.GET.get("day", "").strip()
    if latest_year is not None:
        latest_markets = FarmersMarket.objects.filter(year=latest_year).order_by(
            "market_name", "borough", "street_address"
        )
        for market in latest_markets.values(
            "market_name",
            "borough",
            "street_address",
            "latitude",
            "longitude",
            "days_of_operation",
            "hours_of_operations",
            "season_dates",
        ):
            override = FARMERS_MARKET_LOCATION_OVERRIDES.get(market["market_name"])
            if override:
                market.update(override)
            else:
                market["zip_code"] = ""

            latitude = market["latitude"]
            longitude = market["longitude"]
            if (
                latitude is not None
                and longitude is not None
                and NYC_LATITUDE_RANGE[0] <= latitude <= NYC_LATITUDE_RANGE[1]
                and NYC_LONGITUDE_RANGE[0] <= longitude <= NYC_LONGITUDE_RANGE[1]
                and (not name or name.casefold() in market["market_name"].casefold())
                and (
                    not zipcode
                    or market["zip_code"].startswith(zipcode)
                    or zipcode in market["street_address"]
                )
                and (
                    not day
                    or _market_operates_on_day(market["days_of_operation"], day)
                )
            ):
                markets.append(market)
    return render(
        request,
        "search/farmers_markets_map.html",
        {
            "markets": markets,
            "market_year": latest_year,
            "name": name,
            "zip": zipcode,
            "day": day,
            "day_options": MARKET_DAYS,
        },
    )


def explore(request, slug):
    config = DATASETS.get(slug)
    if config is None:
        raise Http404("Unknown dataset")

    query = request.GET.get("q", "").strip()
    qs = config["model"].objects.order_by("pk")
    if query:
        condition = Q()
        for field in config["search_fields"]:
            condition |= Q(**{field: query})
        qs = qs.filter(condition)

    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [
        [
            "—" if getattr(obj, field) in (None, "") else getattr(obj, field)
            for field, _label in config["columns"]
        ]
        for obj in page_obj
    ]

    return render(
        request,
        "search/explore.html",
        {
            "config": config,
            "slug": slug,
            "query": query,
            "page_obj": page_obj,
            "columns": config["columns"],
            "rows": rows,
        },
    )


def _in_nyc(lat, lng):
    return (
        lat is not None
        and lng is not None
        and NYC_LATITUDE_RANGE[0] <= lat <= NYC_LATITUDE_RANGE[1]
        and NYC_LONGITUDE_RANGE[0] <= lng <= NYC_LONGITUDE_RANGE[1]
    )


def _matches_text(value, query):
    return not query or query.casefold() in (value or "").casefold()


def _matches_zip(value, zipcode):
    return not zipcode or (value or "").startswith(zipcode)


def _combined_static_points(name="", boro="", zipcode=""):
    points = []

    latest_year = FarmersMarket.objects.aggregate(latest_year=Max("year"))[
        "latest_year"
    ]
    if latest_year is not None:
        for market in FarmersMarket.objects.filter(year=latest_year).order_by(
            "market_name"
        ):
            data = {
                "market_name": market.market_name,
                "borough": market.borough,
                "street_address": market.street_address,
                "latitude": market.latitude,
                "longitude": market.longitude,
                "zip_code": "",
            }
            override = FARMERS_MARKET_LOCATION_OVERRIDES.get(market.market_name)
            if override:
                data.update(override)
            if not _in_nyc(data["latitude"], data["longitude"]):
                continue
            if boro and data["borough"] != boro:
                continue
            if not _matches_text(data["market_name"], name):
                continue
            if zipcode and not (
                _matches_zip(data["zip_code"], zipcode)
                or zipcode in (data["street_address"] or "")
            ):
                continue
            points.append(
                {
                    "name": data["market_name"],
                    "lat": data["latitude"],
                    "lng": data["longitude"],
                    "category": "farmers_market",
                    "address": data["street_address"] or "",
                    "url": None,
                }
            )

    stores = HealthyStore.objects.exclude(latitude__isnull=True).exclude(
        longitude__isnull=True
    )
    if boro:
        stores = stores.filter(borough=boro)
    if name:
        stores = stores.filter(store_name__icontains=name)
    if zipcode:
        stores = stores.filter(zip_code__startswith=zipcode)
    for store in stores.order_by("store_name"):
        if not _in_nyc(store.latitude, store.longitude):
            continue
        points.append(
            {
                "name": store.store_name,
                "lat": store.latitude,
                "lng": store.longitude,
                "category": "grocery",
                "address": store.street_address or "",
                "url": None,
            }
        )

    enrichments = PlaceEnrichment.objects.exclude(latitude__isnull=True).exclude(
        longitude__isnull=True
    )
    if name:
        enrichments = enrichments.filter(
            Q(display_name__icontains=name) | Q(camis__icontains=name)
        )
    if zipcode:
        enrichments = enrichments.filter(formatted_address__icontains=zipcode)
    for place in enrichments.order_by("display_name"):
        if not _in_nyc(place.latitude, place.longitude):
            continue
        if boro:
            inspection = (
                RestaurantInspection.objects.filter(camis=place.camis)
                .order_by("-inspection_date")
                .first()
            )
            if inspection is None or inspection.boro != boro:
                continue
        points.append(
            {
                "name": place.display_name or place.camis,
                "lat": place.latitude,
                "lng": place.longitude,
                "category": "restaurant_dohmh",
                "address": place.formatted_address or "",
                "url": reverse("search:restaurant_detail", args=[place.camis]),
            }
        )

    return points


def combined_map(request):
    name = request.GET.get("q", "").strip()
    boro = request.GET.get("boro", "").strip()
    zipcode = request.GET.get("zip", "").strip()
    static_points = _combined_static_points(name=name, boro=boro, zipcode=zipcode)
    return render(
        request,
        "search/combined_map.html",
        {
            "name": name,
            "boro": boro,
            "zip": zipcode,
            "boro_options": BOROUGHS,
            "static_points": static_points,
            "maps_key": os.environ.get("GOOGLE_MAPS_JS_KEY", ""),
            "google_url": reverse("search:combined_map_google"),
            "area_choices": AREA_CHOICES,
            "price_choices": PRICE_CHOICES,
            "diet_choices": DIET_CHOICES,
        },
    )


@require_GET
def combined_map_google(request):
    form = RestaurantFilterForm(request.GET)
    if not form.is_valid():
        return JsonResponse(
            {"error": "Invalid filters.", "points": []},
            status=400,
        )
    data = form.cleaned_data
    try:
        restaurants = get_restaurants(
            area=data["area"],
            prices=data["price"],
            diet=data["diet"],
            lat=data["lat"],
            lng=data["lng"],
            radius_m=form.radius_m,
        )
    except PlacesError as exc:
        return JsonResponse({"error": str(exc), "points": []}, status=502)

    points = [
        {
            "name": restaurant["name"],
            "lat": restaurant["lat"],
            "lng": restaurant["lng"],
            "category": "restaurant_google",
            "address": restaurant.get("address") or "",
            "url": restaurant.get("maps_url") or None,
        }
        for restaurant in restaurants
        if restaurant.get("lat") is not None and restaurant.get("lng") is not None
    ]
    return JsonResponse({"error": "", "points": points})
