import re

from django.db.models import Max, Q, Subquery, OuterRef
from django.http import Http404
from django.shortcuts import render

from search.models import FarmersMarket, RestaurantInspection
from search.registry import DATASETS

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


def index(request):
    return render(
        request,
        "search/index.html",
        {
            "restaurants": [
                {"name": "Juniper & Rye", "cuisine": "Seasonal American", "area": "West Village", "price": "$$", "icon": "🥗", "tone": "sage", "description": "Bright, market driven plates and a relaxed neighborhood feel."},
                {"name": "Little Momo House", "cuisine": "Nepalese", "area": "Jackson Heights", "price": "$", "icon": "🥟", "tone": "peach", "description": "Hand-folded momos, warming soups, and family recipes."},
                {"name": "Saffron Table", "cuisine": "Indian", "area": "Crown Heights", "price": "$$", "icon": "🍛", "tone": "gold", "description": "Spiced, colorful comfort food made for sharing."},
                {"name": "Bluefin Corner", "cuisine": "Japanese", "area": "Midtown", "price": "$$$", "icon": "🍣", "tone": "blue", "description": "A small sushi counter with a thoughtful seasonal menu."},
                {"name": "Forno Rosso", "cuisine": "Italian", "area": "Park Slope", "price": "$$", "icon": "🍕", "tone": "rose", "description": "Wood-fired pizza, handmade pasta, and a lively dining room."},
                {"name": "Café Mariposa", "cuisine": "Mexican", "area": "Astoria", "price": "$", "icon": "🌮", "tone": "lavender", "description": "Fresh tacos and homestyle favorites with a little kick."},
            ],
        },
    )


def restaurant_detail(request, camis):
    inspections = RestaurantInspection.objects.filter(camis=camis).order_by(
        "-inspection_date"
    )
    latest = inspections.first()
    if latest is None:
        raise Http404("Restaurant not found")
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
        },
    )


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
