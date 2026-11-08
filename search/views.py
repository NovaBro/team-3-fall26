from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Max, Q
from django.http import Http404, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from community.keys import DOHMH, dohmh_key
from community.models import CommunitySubject, PlaceEnrichment, PlaceReview
from restaurants.diet_filters import ALLERGY_CHOICES, risky_cuisines
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
from search.menustat import calorie_score_for_name, top_low_calorie_meals
from search.recommend import (
    allergy_keys_from_text,
    home_zip_boro,
    score_restaurant,
    split_foods,
    whole_word_match,
)
from search.services.places import PlacesAPIError, enrich_camis

PAGE_SIZE = 25
POOL_SIZE = 9
MAX_CANDIDATES = 15
FAVORITE_EXTRA = 3
NEARBY_EXTRA = 3


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


def _grade_a_queryset(exclude_cuisines=None):
    qs = (
        RestaurantInspection.objects.filter(grade="A")
        .exclude(dba="")
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
    if exclude_cuisines:
        qs = qs.exclude(cuisine__in=exclude_cuisines)
    return qs


def _profile_for(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    try:
        return user.profile
    except ObjectDoesNotExist:
        return None


def _whole_word_q(food):
    """Case-insensitive whole-word match on cuisine or name (dba)."""
    food = (food or "").strip()
    if not food:
        return Q()
    # SQLite/Postgres: use icontains then filter precisely in Python if needed;
    # for candidate expansion, icontains is enough and then we re-check.
    return Q(cuisine__icontains=food) | Q(name__icontains=food)


def _build_candidate_pool(profile):
    """Up to 9 recent grade-A, plus favorites/nearby extras (max 15)."""
    avoid = allergy_keys_from_text(getattr(profile, "allergies", "") if profile else "")
    excluded = risky_cuisines(avoid) if avoid else set()

    base = list(_grade_a_queryset(excluded).order_by("-last_date")[:POOL_SIZE])
    by_camis = {row["camis"]: row for row in base}

    if profile is not None and len(by_camis) < MAX_CANDIDATES:
        favorites = split_foods(getattr(profile, "favorite_foods", ""))
        added = 0
        for food in favorites:
            if added >= FAVORITE_EXTRA or len(by_camis) >= MAX_CANDIDATES:
                break
            for row in (
                _grade_a_queryset(excluded)
                .filter(_whole_word_q(food))
                .order_by("-last_date")[: FAVORITE_EXTRA * 3]
            ):
                if row["camis"] in by_camis:
                    continue
                if not whole_word_match(food, row.get("cuisine"), row.get("name")):
                    continue
                by_camis[row["camis"]] = row
                added += 1
                if added >= FAVORITE_EXTRA or len(by_camis) >= MAX_CANDIDATES:
                    break

        _home_zip, home_boro = home_zip_boro(getattr(profile, "home_address", ""))
        if home_boro and len(by_camis) < MAX_CANDIDATES:
            nearby_added = 0
            for row in (
                _grade_a_queryset(excluded)
                .filter(boro__iexact=home_boro)
                .order_by("-last_date")[: NEARBY_EXTRA * 3]
            ):
                if row["camis"] in by_camis:
                    continue
                by_camis[row["camis"]] = row
                nearby_added += 1
                if nearby_added >= NEARBY_EXTRA or len(by_camis) >= MAX_CANDIDATES:
                    break

    return list(by_camis.values())[:MAX_CANDIDATES]


def _app_rating_stats(camis):
    subject = CommunitySubject.objects.filter(kind=DOHMH, key=dohmh_key(camis)).first()
    if subject is None:
        return None, 0
    stats = subject.ratings.aggregate(average=Avg("score"), count=Count("id"))
    return stats["average"], stats["count"] or 0


def _reviews_for_pick(google, camis_id):
    reviews = list((google or {}).get("reviews") or [])[:5]
    if reviews:
        return reviews
    if not camis_id:
        return []
    db_reviews = (
        PlaceReview.objects.filter(place__camis=camis_id)
        .exclude(text="")
        .order_by("-id")[:5]
    )
    return [
        {
            "text": r.text,
            "author_name": r.author_name,
            "rating": r.rating,
            "relative_time": r.relative_time,
        }
        for r in db_reviews
    ]


def _top_picks(request, count=3):
    """Score a pool of grade-A restaurants and return the top *count* picks."""
    profile = _profile_for(request)
    picks = _build_candidate_pool(profile)
    if not picks:
        return []

    workers = min(8, max(1, len(picks)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
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
            pick["inspection"] = _latest(pick["camis"])
        pick["image"] = "search/images/nyc-restaurant.jpg"

        camis_id = (pick.get("inspection") or {}).get("camis") or pick.get("camis")
        reviews = _reviews_for_pick(google, camis_id)
        chosen_review = (google or {}).get("review")
        if not chosen_review and reviews:
            chosen_review = reviews[0]
        pick["review"] = chosen_review

        app_avg, app_count = _app_rating_stats(camis_id) if camis_id else (None, 0)
        inspection = pick.get("inspection") or {}
        grade = inspection.get("grade") or "A"
        pick_name = pick.get("name") or ""
        calorie = calorie_score_for_name(pick_name)
        score, tags, _breakdown = score_restaurant(
            name=pick_name,
            cuisine=pick.get("cuisine") or "",
            grade=grade,
            google_rating=(google or {}).get("rating"),
            google_count=(google or {}).get("rating_count") or 0,
            app_avg=app_avg,
            app_count=app_count,
            reviews=reviews,
            price=(google or {}).get("price"),
            zipcode=pick.get("zipcode") or "",
            boro=pick.get("boro") or "",
            profile=profile,
            calorie_score=calorie,
        )
        pick["score"] = score
        pick["reason_tags"] = tags
        pick["calorie_score"] = calorie

    picks.sort(key=lambda p: p.get("score", 0), reverse=True)
    return picks[:count]


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
        top_picks = _top_picks(request, count=3)

    return render(
        request,
        "search/home.html",
        {
            "restaurants": restaurants,
            "page_obj": page_obj,
            "borough_options": borough_options,
            "selected_boro": selected_boro,
            "top_picks": top_picks,
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
    menu_picks, menustat_name = top_low_calorie_meals(latest.dba, limit=5)

    reviews = []
    google_rating = None
    google_count = 0
    price = ""
    if place is not None:
        google_rating = place.rating
        google_count = place.user_rating_count or 0
        price = place.price_level_display or ""
        reviews = [
            {"text": r.text} for r in place.reviews.all() if (r.text or "").strip()
        ][:5]
    app_avg, app_count = _app_rating_stats(camis)
    calorie = calorie_score_for_name(latest.dba)
    grade = (latest.grade or "").strip() or "A"
    healthiness_score, reason_tags, score_breakdown = score_restaurant(
        name=latest.dba or "",
        cuisine=latest.cuisine or "",
        grade=grade,
        google_rating=google_rating,
        google_count=google_count,
        app_avg=app_avg,
        app_count=app_count,
        reviews=reviews,
        price=price,
        zipcode=latest.zipcode or "",
        boro=latest.boro or "",
        profile=_profile_for(request),
        calorie_score=calorie,
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
            "menu_picks": menu_picks,
            "menustat_name": menustat_name,
            "healthiness_score": healthiness_score,
            "reason_tags": reason_tags,
            "score_breakdown": score_breakdown,
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
