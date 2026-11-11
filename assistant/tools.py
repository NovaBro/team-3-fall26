"""Read-only tools Claude can call. Each runs a fixed ORM query.

The user and their location always come from the request, never from tool
arguments. The model never sees the coordinates.
"""

import json
import logging
import re
from urllib.parse import urlencode

from django.db.models import Avg, Count, Max
from django.urls import reverse

from community.keys import DOHMH, GOOGLE
from community.models import CommunitySubject, PlaceEnrichment, UserRating
from restaurants.places import METERS_PER_MILE, PlacesError
from search.find_food import (
    farmers_market_items,
    fill_latest_grades,
    google_restaurant_items,
    grocery_items,
    near,
    restaurant_item,
    restaurant_rows,
)
from search.forms import FARMERS_MARKET, GROCERY, MARKET_DAYS, RESTAURANT
from search.models import MenuItem, RestaurantInspection

logger = logging.getLogger(__name__)

MAX_RESULTS = 15
DEFAULT_RESULTS = 8
STORE_TYPES = [RESTAURANT, FARMERS_MARKET, GROCERY]
BOROUGHS = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"]
GRADES = ["A", "B", "C"]
DEFAULT_NEARBY_MILES = 1.0
MAX_NEARBY_MILES = 5.0
MAX_GOOGLE_SEARCHES = 2  # Per chat message. Each one is a paid Google request.
MENU_SORTS = ["lowest_calories", "highest_protein"]
HIDDEN_MENU_CATEGORIES = ("Beverages", "Toppings & Ingredients")
KEEP_UPPER = {"NYC", "BBQ", "LLC", "INC", "USA", "NY", "BK", "II", "III", "KFC"}

TOOLS = [
    {
        "name": "search_places",
        "description": (
            "Search NYC restaurants, farmers markets, and Shop Healthy grocery "
            "stores. Normally searches inspection records and favors grade A. "
            "With near_me, restaurants come from a live Google search around the "
            "user, nearest first, with distance, rating, and price. Allergies and "
            "diets aren't filtered, so choose from the results yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": STORE_TYPES},
                    "description": "Defaults to restaurants if cuisine or grade "
                    "is used, otherwise all three.",
                },
                "name": {"type": "string", "description": "Part of a place's name."},
                "cuisine": {
                    "type": "string",
                    "description": "A cuisine such as Italian, Thai, or Pizza.",
                },
                "borough": {"type": "string", "enum": BOROUGHS},
                "zip": {"type": "string", "description": "ZIP code or its prefix."},
                "grade": {"type": "string", "enum": GRADES},
                "near_me": {
                    "type": "boolean",
                    "description": "Search around the user's current location.",
                },
                "max_miles": {
                    "type": "number",
                    "description": "How far near_me reaches. Defaults to 1, up to 5.",
                },
                "market_day": {
                    "type": "string",
                    "enum": MARKET_DAYS,
                    "description": "Farmers markets open on this day.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_place_details",
        "description": (
            "Get more about one place using a key from search_places: inspection "
            "history, recent violations, Google data, and visitor ratings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_menu_nutrition",
        "description": (
            "Look up calories and nutrients for menu items at large chains, from "
            "the latest year of NYC MenuStat data. Independent restaurants aren't "
            "covered. Beverages and toppings are hidden unless requested as "
            "food_category. Categories include Entrees, Sandwiches, Salads, "
            "Burgers, Pizza, Soup, Appetizers & Sides, Desserts, and Baked Goods."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chain": {"type": "string", "description": "Part of a chain's name."},
                "food_category": {"type": "string"},
                "max_calories": {"type": "number"},
                "min_protein": {"type": "number", "description": "Grams."},
                "max_sodium": {"type": "number", "description": "Milligrams."},
                "sort": {
                    "type": "string",
                    "enum": MENU_SORTS,
                    "description": "Defaults to lowest_calories.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_my_ratings",
        "description": "Get the places this user has rated, newest first.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


class ToolError(Exception):
    """A bad tool call. The message goes back to the model."""


def display_text(text):
    """NYC datasets shout: MORRIS PARK BAKE SHOP becomes Morris Park Bake Shop."""

    def fix(match):
        word = match.group(0)
        return word if word in KEEP_UPPER else word[0] + word[1:].lower()

    return re.sub(r"[A-Z][A-Z']+", fix, text or "")


def _limit(args):
    try:
        limit = int(args.get("limit") or DEFAULT_RESULTS)
    except (TypeError, ValueError):
        raise ToolError("limit must be a whole number.")
    return max(1, min(limit, MAX_RESULTS))


def _radius_m(args):
    try:
        miles = float(args.get("max_miles") or DEFAULT_NEARBY_MILES)
    except (TypeError, ValueError):
        raise ToolError("max_miles must be a number.")
    return max(0.1, min(miles, MAX_NEARBY_MILES)) * METERS_PER_MILE


def _choice(args, name, allowed):
    value = args.get(name)
    if value and value not in allowed:
        raise ToolError(f"{name} must be one of: {', '.join(allowed)}.")
    return value or ""


def _choices(args, name, allowed):
    values = args.get(name) or []
    if not isinstance(values, list) or any(value not in allowed for value in values):
        raise ToolError(f"{name} must only contain: {', '.join(allowed)}.")
    return values


def enrichment_by_camis(camis_list):
    return {
        row.camis: row for row in PlaceEnrichment.objects.filter(camis__in=camis_list)
    }


def add_google_fields(summary, enrichment):
    if enrichment is None:
        return
    if enrichment.rating is not None:
        summary["google_rating"] = enrichment.rating
        summary["google_rating_count"] = enrichment.user_rating_count
    if enrichment.price_level_display:
        summary["price"] = enrichment.price_level_display


def available_cuisines():
    return list(
        RestaurantInspection.objects.exclude(cuisine="")
        .values_list("cuisine", flat=True)
        .distinct()
        .order_by("cuisine")
    )


class ToolRunner:
    """Runs tool calls for one user and remembers which places they returned."""

    def __init__(self, user, location=None):
        self.user = user
        self.location = location
        self.google_searches = 0
        self.places = {}

    def run(self, name, args):
        """Return (JSON text, is_error) for a tool call."""
        handlers = {
            "search_places": self.search_places,
            "get_place_details": self.get_place_details,
            "get_menu_nutrition": self.get_menu_nutrition,
            "get_my_ratings": self.get_my_ratings,
        }
        try:
            if name not in handlers:
                raise ToolError(f"Unknown tool: {name}.")
            return json.dumps(handlers[name](args or {}), default=str), False
        except ToolError as error:
            return str(error), True
        except Exception:
            logger.exception("Assistant tool %s failed", name)
            return "This lookup failed. Tell the user you couldn't check it.", True

    def _summary(self, item):
        # Google names are already well formatted. Only dataset names shout.
        name = item["name"] if item["kind"] == GOOGLE else display_text(item["name"])
        summary = {
            "key": item["key"],
            "type": item["type_label"],
            "name": name,
            "address": display_text(item["address"]),
            "borough": display_text(item["borough"]),
            "details": item["details"],
        }
        if item["grade"]:
            summary["inspection_grade"] = item["grade"]
        if item["distance_mi"] is not None:
            summary["distance_miles"] = round(item["distance_mi"], 2)
        if item["rating"] is not None:
            summary["google_rating"] = item["rating"]
            summary["google_rating_count"] = item["rating_count"]
        if item["price"]:
            summary["price"] = item["price"]
        url = item["url"] or (
            reverse("search:index")
            + "?"
            + urlencode({"types": item["kind"], "q": name})
        )
        self.places[item["key"]] = {
            "key": item["key"],
            "name": name,
            "type": item["type_label"],
            "address": summary["address"],
            "grade": item["grade"],
            "distance_miles": summary.get("distance_miles"),
            "url": url,
            "external": item["external_url"],
        }
        return summary

    def search_places(self, args):
        cuisine = str(args.get("cuisine") or "").strip()
        borough = _choice(args, "borough", BOROUGHS)
        grade = _choice(args, "grade", GRADES)
        market_day = _choice(args, "market_day", MARKET_DAYS)
        zip_code = str(args.get("zip") or "").strip()
        if zip_code and not re.fullmatch(r"\d{1,5}", zip_code):
            raise ToolError("zip must be up to 5 digits.")
        types = _choices(args, "types", STORE_TYPES)
        if not types:
            types = [RESTAURANT] if cuisine or grade else STORE_TYPES
        limit = _limit(args)
        filters = {
            "q": str(args.get("name") or "").strip(),
            "area": borough,
            "zip": zip_code,
            "cuisine": cuisine,
            "grade": grade,
            "day": market_day,
        }
        near_me = bool(args.get("near_me"))
        if near_me and self.location is None:
            return {
                "places": [],
                "note": (
                    "The user's location isn't available. Use a ZIP code or borough, "
                    "or suggest the Use my location button."
                ),
            }
        radius_m = _radius_m(args) if near_me else None

        result = {"places": []}
        if RESTAURANT in types:
            if near_me:
                result["places"] += self._nearby_restaurants(
                    filters, result, limit, radius_m
                )
            else:
                result["places"] += self._restaurants(filters, limit)
        if FARMERS_MARKET in types:
            items = self._nearest(farmers_market_items(filters), radius_m)[:limit]
            result["places"] += [self._summary(item) for item in items]
        if GROCERY in types:
            items = self._nearest(grocery_items(filters), radius_m)[:limit]
            result["places"] += [self._summary(item) for item in items]
        if cuisine and not result["places"] and not near_me:
            result["available_cuisines"] = available_cuisines()
        if near_me and not result["places"] and "note" not in result:
            result["note"] = "Nothing found in that range. Try a larger max_miles."
        return result

    def _nearest(self, items, radius_m):
        if radius_m is None:
            return items
        return near(items, self.location[0], self.location[1], radius_m)

    def _nearby_restaurants(self, filters, result, limit, radius_m):
        if self.google_searches >= MAX_GOOGLE_SEARCHES:
            result["note"] = (
                "The nearby search limit for this message was reached. Answer with "
                "what you have."
            )
            return []
        self.google_searches += 1
        data = {
            **filters,
            "price": [],
            "diet": "",
            "avoid": [],
            "open_now": False,
            "min_rating": "",
            "lat": self.location[0],
            "lng": self.location[1],
        }
        try:
            items = google_restaurant_items(data, radius_m)
        except PlacesError:
            logger.warning("Assistant nearby search failed", exc_info=True)
            result["note"] = (
                "Nearby search isn't working right now. Ask for a ZIP code or "
                "borough instead."
            )
            return []
        return [self._summary(item) for item in items[:limit]]

    def _restaurants(self, filters, limit):
        # Look past the first page so grade A places can rise to the top.
        rows = restaurant_rows(filters).order_by("-last_date", "camis")[: limit * 4]
        items = [restaurant_item(row) for row in rows]
        fill_latest_grades(items)
        items.sort(key=lambda item: item["grade"] != "A")
        items = items[:limit]
        enrichment = enrichment_by_camis([i["key"].split(":", 1)[1] for i in items])
        places = []
        for item in items:
            summary = self._summary(item)
            add_google_fields(summary, enrichment.get(item["key"].split(":", 1)[1]))
            places.append(summary)
        return places

    def get_place_details(self, args):
        key = str(args.get("key") or "")
        if key.startswith("google:"):
            raise ToolError(
                "This place came from a live Google search, so the search result "
                "is all we have."
            )
        if key.startswith("camis:"):
            return self._restaurant_details(key)
        for item in [*farmers_market_items({}), *grocery_items({})]:
            if item["key"] == key:
                summary = self._summary(item)
                summary.update(self._visitor_ratings(item["kind"], key))
                return summary
        raise ToolError("No place has that key. Use a key from search_places.")

    def _restaurant_details(self, key):
        camis = key.split(":", 1)[1]
        rows = list(
            RestaurantInspection.objects.filter(camis=camis).order_by(
                "-inspection_date"
            )
        )
        if not rows:
            raise ToolError("No place has that key. Use a key from search_places.")
        latest = rows[0]
        item = restaurant_item(
            {
                "camis": camis,
                "name": latest.dba,
                "boro": latest.boro,
                "street": latest.street,
                "zip": latest.zipcode,
                "cuisine_name": latest.cuisine,
                "last_date": latest.inspection_date,
            }
        )
        fill_latest_grades([item])
        summary = self._summary(item)
        summary["recent_violations"] = [
            row.violation_description[:200]
            for row in rows
            if row.inspection_date == latest.inspection_date
            and row.violation_description
        ][:5]
        enrichment = PlaceEnrichment.objects.filter(camis=camis).first()
        add_google_fields(summary, enrichment)
        if enrichment is not None:
            summary["recent_reviews"] = [
                {"rating": review.rating, "text": review.text[:300]}
                for review in enrichment.reviews.exclude(text="")[:3]
            ]
        summary.update(self._visitor_ratings(DOHMH, key))
        return summary

    def _visitor_ratings(self, kind, key):
        stats = (
            CommunitySubject.objects.filter(kind=kind, key=key)
            .annotate(average=Avg("ratings__score"), total=Count("ratings"))
            .values("average", "total")
            .first()
        )
        if not stats or not stats["total"]:
            return {}
        return {
            "visitor_rating": round(stats["average"], 1),
            "visitor_rating_count": stats["total"],
        }

    def get_menu_nutrition(self, args):
        chain = str(args.get("chain") or "").strip()
        category = str(args.get("food_category") or "").strip()
        limit = _limit(args)
        items = MenuItem.objects.exclude(calories=None)
        if chain:
            items = items.filter(restaurant__icontains=chain)
            if not items.exists():
                return {
                    "items": [],
                    "note": f"No nutrition data for {chain}.",
                    "available_chains": list(
                        MenuItem.objects.values_list("restaurant", flat=True)
                        .distinct()
                        .order_by("restaurant")
                    ),
                }
        if category:
            items = items.filter(food_category__iexact=category)
        else:
            items = items.exclude(food_category__in=HIDDEN_MENU_CATEGORIES)
        for field, lookup in (
            ("max_calories", "calories__lte"),
            ("min_protein", "protein__gte"),
            ("max_sodium", "sodium__lte"),
        ):
            if args.get(field) is not None:
                try:
                    items = items.filter(**{lookup: float(args[field])})
                except (TypeError, ValueError):
                    raise ToolError(f"{field} must be a number.")
        year = items.aggregate(latest=Max("year"))["latest"]
        items = items.filter(year=year)
        sort = _choice(args, "sort", MENU_SORTS) or MENU_SORTS[0]
        if sort == "highest_protein":
            items = items.exclude(protein=None)
        order = "-protein" if sort == "highest_protein" else "calories"
        seen = set()
        found = []
        for row in items.order_by(order)[: limit * 3]:
            identity = (row.restaurant, row.item_name)
            if identity in seen:
                continue
            seen.add(identity)
            found.append(
                {
                    "chain": row.restaurant,
                    "item": row.item_name,
                    "category": row.food_category,
                    "calories": row.calories,
                    "protein_g": row.protein,
                    "fat_g": row.total_fat,
                    "carbs_g": row.carbohydrates,
                    "sugar_g": row.sugar,
                    "sodium_mg": row.sodium,
                }
            )
        return {"data_year": year, "items": found[:limit]}

    def get_my_ratings(self, args):
        ratings = (
            UserRating.objects.filter(user_id=self.user.id)
            .select_related("subject")
            .order_by("-updated_at")[:20]
        )
        return {
            "ratings": [
                {
                    "key": rating.subject.key,
                    "name": display_text(rating.subject.name),
                    "score": rating.score,
                }
                for rating in ratings
            ]
        }
