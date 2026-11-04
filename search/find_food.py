"""Results for the Find food page: farmers markets, grocery stores and
restaurants as one list of "items" that the template and the map share.

Every item is a dict with the same keys (see ``_item``). ``kind`` and ``key``
are the community pin identity, so reviews, ratings and photos keep working.
"""

import re

from django.db.models import Max, OuterRef, Subquery
from django.urls import reverse
from urllib.parse import urlencode

from community.keys import (
    DOHMH,
    FARMERS_MARKET,
    GOOGLE,
    GROCERY,
    dohmh_key,
    farmers_market_key,
    google_key,
    grocery_key,
)
from restaurants.diet_filters import DIETS, risky_cuisines
from restaurants.inspections import attach_inspections, google_zip
from restaurants.places import METERS_PER_MILE, distance_m, get_restaurants
from search.forms import MARKET_DAYS
from search.locations import cached_lookups, enrichment_coordinates, resolve
from search.models import FarmersMarket, HealthyStore, RestaurantInspection

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
# Shop Healthy lists some Manhattan stores under the borough "New York".
BOROUGH_ALIASES = {"Manhattan": ["Manhattan", "New York"]}
TYPE_LABELS = {
    FARMERS_MARKET: "Farmers market",
    GROCERY: "Grocery",
    DOHMH: "Restaurant",
    GOOGLE: "Restaurant",
}
MARKET_DAY_PATTERN = re.compile(
    r"\b(Mondays?|Mon|Tuesdays?|Tues?|Wednesdays?|Weds?|"
    r"Thursdays?|Thurs?|Fridays?|Fris?|Saturdays?|Sats?|Sundays?|Suns?)\b",
    re.IGNORECASE,
)
ZIP_PATTERN = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def in_nyc(lat, lng):
    return (
        lat is not None
        and lng is not None
        and NYC_LATITUDE_RANGE[0] <= lat <= NYC_LATITUDE_RANGE[1]
        and NYC_LONGITUDE_RANGE[0] <= lng <= NYC_LONGITUDE_RANGE[1]
    )


def _day_index(word):
    prefix = word.casefold()[:3]
    return next(
        (n for n, day in enumerate(MARKET_DAYS) if day.casefold().startswith(prefix)),
        None,
    )


def market_operates_on_day(days_of_operation, selected_day):
    """True if text like "Mon-Wed, Sat" includes ``selected_day``."""
    text = days_of_operation or ""
    matches = list(MARKET_DAY_PATTERN.finditer(text))
    found = set()
    for index, match in enumerate(matches):
        start = _day_index(match.group())
        if start is None:
            continue
        found.add(start)
        if index + 1 < len(matches):
            between = text[match.end() : matches[index + 1].start()]  # noqa: E203
            end = _day_index(matches[index + 1].group())
            if end is not None and re.fullmatch(r"\s*[-–]\s*", between):
                current = start
                while current != end:
                    current = (current + 1) % len(MARKET_DAYS)
                    found.add(current)
    return selected_day in MARKET_DAYS and MARKET_DAYS.index(selected_day) in found


def _item(kind, key, name, **fields):
    item = {
        "kind": kind,
        "category": kind,
        "type_label": TYPE_LABELS[kind],
        "key": key,
        "name": name or "(no name)",
        "address": "",
        "borough": "",
        "zipcode": "",
        "lat": None,
        "lng": None,
        "location_source": None,
        "url": "",
        "external_url": False,
        "details": [],
        "grade": "",
        "grade_url": "",
        "has_inspection": None,
        "price": "",
        "rating": None,
        "rating_count": None,
        "photo_url": "",
        "distance_mi": None,
        "locate_query": "",
    }
    item.update(fields)
    if in_nyc(item["lat"], item["lng"]):
        item["location_source"] = item["location_source"] or "dataset"
    else:
        item["lat"] = item["lng"] = None
    return item


def _query(*parts):
    return " ".join(str(part).strip() for part in parts if part).strip()


def _boroughs(area):
    return BOROUGH_ALIASES.get(area, [area])


# --- Farmers markets -------------------------------------------------------


def farmers_market_items(data):
    latest_year = FarmersMarket.objects.aggregate(latest=Max("year"))["latest"]
    if latest_year is None:
        return []
    markets = FarmersMarket.objects.filter(year=latest_year).order_by(
        "market_name", "borough", "street_address"
    )
    if data.get("area"):
        markets = markets.filter(borough__in=_boroughs(data["area"]))
    if data.get("q"):
        markets = markets.filter(market_name__icontains=data["q"])

    items = []
    for market in markets:
        override = FARMERS_MARKET_LOCATION_OVERRIDES.get(market.market_name, {})
        address = override.get("street_address", market.street_address)
        zip_match = ZIP_PATTERN.search(address or "")
        zipcode = override.get("zip_code") or (zip_match.group(1) if zip_match else "")
        if data.get("zip") and not (
            zipcode.startswith(data["zip"]) or data["zip"] in (address or "")
        ):
            continue
        if data.get("day") and not market_operates_on_day(
            market.days_of_operation, data["day"]
        ):
            continue
        details = [
            text
            for text in (
                market.days_of_operation,
                market.hours_of_operations,
                market.season_dates,
                "Accepts EBT" if market.accepts_ebt.casefold() == "yes" else "",
            )
            if text
        ]
        items.append(
            _item(
                FARMERS_MARKET,
                farmers_market_key(
                    market.year, market.market_name, market.street_address
                ),
                market.market_name,
                address=address or "",
                borough=market.borough,
                zipcode=zipcode,
                lat=override.get("latitude", market.latitude),
                lng=override.get("longitude", market.longitude),
                details=details,
                locate_query=_query(market.market_name, address, market.borough, "NY"),
            )
        )
    return items


# --- Grocery (Shop Healthy) ------------------------------------------------


def grocery_items(data):
    stores = HealthyStore.objects.order_by("store_name", "street_address")
    if data.get("area"):
        stores = stores.filter(borough__in=_boroughs(data["area"]))
    if data.get("q"):
        stores = stores.filter(store_name__icontains=data["q"])
    if data.get("zip"):
        stores = stores.filter(zip_code__startswith=data["zip"])
    return [
        _item(
            GROCERY,
            grocery_key(store.store_name, store.street_address, store.zip_code),
            store.store_name,
            address=store.street_address,
            borough="Manhattan" if store.borough == "New York" else store.borough,
            zipcode=store.zip_code,
            lat=store.latitude,
            lng=store.longitude,
            details=(
                [f"Shop Healthy since {store.year_awarded}"]
                if store.year_awarded
                else []
            ),
            locate_query=_query(
                store.store_name, store.street_address, store.borough, "NY"
            )
            + (f" {store.zip_code}" if store.zip_code else ""),
        )
        for store in stores
    ]


# --- Restaurants from inspection records -----------------------------------


def restaurant_rows(data):
    """One row per restaurant (camis) matching the filters.

    The newest grade is only computed in SQL when filtering by grade (it is a
    subquery per restaurant); otherwise ``fill_latest_grades`` adds it for the
    rows actually shown.
    """
    qs = RestaurantInspection.objects.exclude(dba="")
    if data.get("q"):
        qs = qs.filter(dba__icontains=data["q"])
    if data.get("area"):
        qs = qs.filter(boro=data["area"])
    if data.get("zip"):
        qs = qs.filter(zipcode__startswith=data["zip"])
    if data.get("cuisine"):
        qs = qs.filter(cuisine__istartswith=data["cuisine"])
    if data.get("diet"):
        qs = qs.filter(cuisine__in=DIETS[data["diet"]]["cuisines"] or [])
    if data.get("avoid"):
        qs = qs.exclude(cuisine__in=risky_cuisines(data["avoid"]))

    rows = qs.values("camis").annotate(
        name=Max("dba"),
        boro=Max("boro"),
        street=Max("street"),
        zip=Max("zipcode"),
        cuisine_name=Max("cuisine"),
        last_date=Max("inspection_date"),
    )
    if data.get("grade"):
        graded = (
            RestaurantInspection.objects.filter(camis=OuterRef("camis"))
            .exclude(grade="")
            .order_by("-inspection_date")
        )
        rows = rows.annotate(latest_grade=Subquery(graded.values("grade")[:1]))
        rows = rows.filter(latest_grade=data["grade"])
    return rows.order_by("name", "camis")


def fill_latest_grades(items):
    """Set the newest non-blank inspection grade on inspection-record items."""
    camis = {
        item["key"].split(":", 1)[1]: item for item in items if item["kind"] == DOHMH
    }
    if not camis:
        return
    seen = set()
    rows = (
        RestaurantInspection.objects.filter(camis__in=list(camis))
        .exclude(grade="")
        .order_by("camis", "-inspection_date")
        .values_list("camis", "grade")
    )
    for key, grade in rows:
        if key not in seen:
            seen.add(key)
            camis[key]["grade"] = grade


def restaurant_item(row):
    url = reverse("search:restaurant_detail", args=[row["camis"]])
    details = [row["cuisine_name"]] if row["cuisine_name"] else []
    if row["last_date"]:
        details.append(f"Inspected {row['last_date']:%b %Y}")
    return _item(
        DOHMH,
        dohmh_key(row["camis"]),
        row["name"],
        address=_query(row["street"], row["boro"], row["zip"]),
        borough=row["boro"],
        zipcode=row["zip"],
        url=url,
        details=details,
        grade=row.get("latest_grade") or "",
        grade_url=url,
        has_inspection=True,
        locate_query=_query(row["name"], row["street"], row["boro"], "NY", row["zip"]),
    )


def located_restaurant_items(rows):
    """Matching restaurants whose coordinates are already stored (no API calls)."""
    camis = set(enrichment_coordinates())
    camis.update(
        key.split(":", 1)[1]
        for key, row in cached_lookups(DOHMH).items()
        if row.found and key.startswith("camis:")
    )
    if not camis:
        return []
    items = [restaurant_item(row) for row in rows.filter(camis__in=camis)]
    resolve(items, fetch=False)
    return [item for item in items if item["lat"] is not None]


# --- Restaurants from Google Places ----------------------------------------


def _photo_url(photo):
    if not photo:
        return ""
    return reverse("restaurants:photo") + "?" + urlencode({"name": photo})


def google_restaurant_items(data, radius_m):
    """Live Google Places results (raises PlacesError), filtered like the
    inspection records where Google has no matching filter."""
    places = attach_inspections(
        get_restaurants(
            cuisine=data["cuisine"],
            area=data["area"],
            prices=data["price"],
            diet=data["diet"],
            lat=data["lat"],
            lng=data["lng"],
            radius_m=radius_m,
            avoid=data["avoid"],
            open_now=data["open_now"],
            min_rating=float(data["min_rating"]) if data["min_rating"] else None,
        )
    )
    items = []
    for place in places:
        inspection = place.get("inspection") or {}
        zipcode = place.get("zipcode") or google_zip(place.get("address"))
        if data.get("q") and data["q"].casefold() not in place["name"].casefold():
            continue
        if data.get("zip") and not (zipcode or "").startswith(data["zip"]):
            continue
        if data.get("grade") and inspection.get("grade") != data["grade"]:
            continue
        detail_url = (
            reverse("search:restaurant_detail", args=[inspection["camis"]])
            if inspection
            else ""
        )
        details = []
        if place.get("vegetarian") is True:
            details.append("Vegetarian options")
        items.append(
            _item(
                GOOGLE,
                google_key(place.get("id") or place["name"]),
                place["name"],
                address=place.get("address", ""),
                zipcode=zipcode or "",
                lat=place.get("lat"),
                lng=place.get("lng"),
                location_source="google",
                url=place.get("maps_url", ""),
                external_url=bool(place.get("maps_url")),
                details=details,
                grade=inspection.get("grade", ""),
                grade_url=detail_url,
                has_inspection=bool(inspection),
                price=place.get("price", ""),
                rating=place.get("rating"),
                rating_count=place.get("rating_count"),
                photo_url=_photo_url(place.get("photo")),
                distance_mi=place.get("distance_mi"),
            )
        )
    return items


# --- Shared helpers --------------------------------------------------------


def set_distances(items, lat, lng):
    for item in items:
        if item["lat"] is not None and lat is not None:
            item["distance_mi"] = (
                distance_m(lat, lng, item["lat"], item["lng"]) / METERS_PER_MILE
            )


def near(items, lat, lng, radius_m):
    """Items with distances set, inside ``radius_m`` if given, nearest first."""
    if lat is None:
        return items
    set_distances(items, lat, lng)
    if radius_m:
        limit = radius_m / METERS_PER_MILE
        items = [
            item
            for item in items
            if item["distance_mi"] is not None and item["distance_mi"] <= limit
        ]
    return sorted(
        items, key=lambda item: (item["distance_mi"] is None, item["distance_mi"] or 0)
    )


def map_point(item):
    return {
        "name": item["name"],
        "lat": item["lat"],
        "lng": item["lng"],
        "category": item["category"],
        "kind": item["kind"],
        "key": item["key"],
        "address": item["address"],
        "url": item["url"],
    }


class Chain:
    """Several sequences read as one, so a Paginator can page across them.

    Each segment is ``(sequence, transform)``; querysets are counted with
    ``.count()`` and only the requested slice is fetched.
    """

    def __init__(self, *segments):
        self.segments = segments
        self._lengths = None

    def lengths(self):
        if self._lengths is None:
            self._lengths = [
                seq.count() if hasattr(seq, "query") else len(seq)
                for seq, _transform in self.segments
            ]
        return self._lengths

    def __len__(self):
        return sum(self.lengths())

    def __getitem__(self, index):
        if not isinstance(index, slice):
            return self[index : index + 1][0]  # noqa: E203
        start, stop, _step = index.indices(len(self))
        out, offset = [], 0
        for (seq, transform), length in zip(self.segments, self.lengths()):
            lo, hi = max(start - offset, 0), min(stop - offset, length)
            if lo < hi:
                out.extend(transform(row) for row in seq[lo:hi])
            offset += length
        return out
