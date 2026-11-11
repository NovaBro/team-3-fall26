import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import (
    Avg,
    BigIntegerField,
    Case,
    CharField,
    Count,
    IntegerField,
    Max,
    Q,
    When,
)
from django.db.models.functions import Cast, Concat, Mod, Right
from django.http import Http404, QueryDict
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.views.decorators.http import require_POST

from assistant.recommend import personalized_picks
from community.keys import DOHMH, dohmh_key
from community.models import (
    CommunitySubject,
    PlaceEnrichment,
    PlaceReview,
    RecommendationFeedback,
    UserRating,
)
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
    FAST_FOOD_PREFIXES,
    HEALTHY_CUISINES,
    NON_MEAL_CUISINES,
    NON_MEAL_PREFIXES,
    UNHEALTHY_CUISINES,
    allergy_keys_from_text,
    build_feedback_prefs,
    daily_seed,
    home_zip_boro,
    pick_display_review,
    pick_top,
    score_restaurant,
    split_foods,
    whole_word_match,
)
from search.services.places import PlacesAPIError, enrich_camis

PAGE_SIZE = 25
POOL_SIZE = 9  # candidates scored per day (one Google lookup each)
PICKS_TIME_ZONE = ZoneInfo("America/New_York")
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


def _name_starts_with(prefixes):
    """Q for an annotated ``name`` that starts with any brand in *prefixes*."""
    query = Q()
    for prefix in prefixes:
        query |= (
            Q(name__iexact=prefix)
            | Q(name__istartswith=prefix + " ")
            | Q(name__istartswith=prefix + "#")
        )
    return query


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


def _today():
    return datetime.now(PICKS_TIME_ZONE).date()


def _feedback_prefs(request):
    """The viewer's Like / Not interested buttons and star ratings, or None."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    explicit = list(
        RecommendationFeedback.objects.filter(user_id=user.pk).values_list(
            "camis", "name", "cuisine", "value"
        )
    )
    stars = {
        key.removeprefix("camis:"): score
        for key, score in UserRating.objects.filter(
            user_id=user.pk, subject__kind=DOHMH
        ).values_list("subject__key", "score")
    }
    star_ratings = []
    if stars:
        rows = (
            RestaurantInspection.objects.filter(camis__in=stars)
            .values("camis")
            .annotate(name=Max("dba"), cuisine=Max("cuisine"))
        )
        star_ratings = [
            (row["camis"], row["name"], row["cuisine"], stars[row["camis"]])
            for row in rows
        ]
    return build_feedback_prefs(explicit, star_ratings)


def _build_candidate_pool(profile, prefs=None, seed="", boro=""):
    """Top picks candidates: the 9 best places by the DB-only health score
    (latest grade A, meals only), shuffled daily within each score tier, plus
    favorites/nearby extras (max 15). Places marked not interested and cuisines
    risky for the user's allergies are skipped. With *boro*, every candidate
    comes from that borough."""
    avoid = allergy_keys_from_text(getattr(profile, "allergies", "") if profile else "")
    excluded = risky_cuisines(avoid) if avoid else set()
    hidden = prefs.hidden if prefs is not None else set()
    multiplier = _shuffle_multiplier(seed)

    def meal_places(in_boro=boro):
        # Latest grade A, places for a meal only (no coffee, bakeries, desserts).
        rows = (
            _scored_restaurants(multiplier)
            .filter(latest_grade="A")
            .exclude(cuisine__in=NON_MEAL_CUISINES | set(excluded))
            .exclude(_name_starts_with(NON_MEAL_PREFIXES))
            .exclude(camis__in=hidden)
        )
        if in_boro:
            rows = rows.filter(boro__iexact=in_boro)
        return rows.order_by("-explore_score", "shuffle", "camis")

    base = list(meal_places()[:POOL_SIZE])
    by_camis = {row["camis"]: row for row in base}

    if profile is not None and len(by_camis) < MAX_CANDIDATES:
        favorites = split_foods(getattr(profile, "favorite_foods", ""))
        added = 0
        for food in favorites:
            if added >= FAVORITE_EXTRA or len(by_camis) >= MAX_CANDIDATES:
                break
            for row in meal_places().filter(_whole_word_q(food))[: FAVORITE_EXTRA * 3]:
                if row["camis"] in by_camis or row["camis"] in hidden:
                    continue
                if not whole_word_match(food, row.get("cuisine"), row.get("name")):
                    continue
                by_camis[row["camis"]] = row
                added += 1
                if added >= FAVORITE_EXTRA or len(by_camis) >= MAX_CANDIDATES:
                    break

        _home_zip, home_boro = home_zip_boro(getattr(profile, "home_address", ""))
        if boro and home_boro.casefold() != boro.casefold():
            home_boro = ""  # another borough is selected; home extras don't apply
        if home_boro and len(by_camis) < MAX_CANDIDATES:
            nearby_added = 0
            for row in meal_places(home_boro)[: NEARBY_EXTRA * 3]:
                if row["camis"] in by_camis or row["camis"] in hidden:
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


def _claude_picks(request, count):
    """Rows for Claude's personalized picks (#129), in Claude's order, each with
    an ``ai_reason``. Empty when Claude isn't configured or the call failed."""
    user = getattr(request, "user", None)
    ai_picks = personalized_picks(user, count) if user is not None else []
    if not ai_picks:
        return []
    reasons = {pick["camis"]: pick["reason"] for pick in ai_picks}
    rows = {
        row["camis"]: row
        for row in _scored_restaurants(1).filter(camis__in=list(reasons))
    }
    picks = [rows[camis] for camis in reasons if camis in rows]
    for pick in picks:
        pick["ai_reason"] = reasons[pick["camis"]]
    return picks


def _top_picks(request, count=3, boro=""):
    """Return the top *count* picks.

    Logged-in users with a profile get Claude's ranking when it's available and
    no borough is selected (places they marked "Not interested" are dropped).
    Otherwise the daily healthy candidate pool is scored and the best picks
    with different cuisines are kept. Either way each pick gets the score and
    reason tags."""
    profile = _profile_for(request)
    prefs = _feedback_prefs(request)
    user_id = request.user.pk if request.user.is_authenticated else None
    hidden = prefs.hidden if prefs is not None else set()
    picks = [] if boro else _claude_picks(request, count)
    picks = [pick for pick in picks if pick["camis"] not in hidden]
    ranked_by_claude = bool(picks)
    if not ranked_by_claude:
        seed = f"{daily_seed(_today(), user_id)}:{boro.casefold()}"
        picks = _build_candidate_pool(profile, prefs, seed, boro)
    if not picks:
        return []
    feedback_values = {}
    if user_id is not None:
        feedback_values = dict(
            RecommendationFeedback.objects.filter(
                user_id=user_id, camis__in=[p["camis"] for p in picks]
            ).values_list("camis", "value")
        )

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
        # Show the review that best explains a healthy pick (see recommend.py).
        pick["review"] = pick_display_review(reviews, profile)

        app_avg, app_count = _app_rating_stats(camis_id) if camis_id else (None, 0)
        inspection = pick.get("inspection") or {}
        grade = inspection.get("grade") or "A"
        pick_name = pick.get("name") or ""
        calorie = calorie_score_for_name(pick_name)
        score, tags, breakdown = score_restaurant(
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
            feedback=prefs,
            camis=pick["camis"],
        )
        pick["score"] = score
        pick["reason_tags"] = tags
        pick["calorie_score"] = calorie
        pick["like_bonus"] = breakdown["like_bonus"]
        pick["feedback"] = feedback_values.get(pick["camis"], 0)

    if ranked_by_claude:
        return picks[:count]  # keep Claude's order
    return pick_top(picks, count)


SHUFFLE_MODULUS = 2_147_483_647  # prime, so each daily multiplier is a new order


def _shuffle_multiplier(seed):
    """A seed-specific multiplier: (camis * multiplier) % prime is a new order."""
    digest = hashlib.sha256(str(seed).encode("utf-8")).hexdigest()
    return 1 + int(digest, 16) % (SHUFFLE_MODULUS - 1)


def _scored_restaurants(multiplier):
    """One row per restaurant with a DB-only health score (no Google lookups).

    explore_score: latest grade A +2 / B +1, healthy cuisine +1, unhealthy or
    non-meal cuisine (coffee, desserts, ...) -1, coffee / dessert chain filed
    under another cuisine -1, fast-food chain -2. ``shuffle`` orders ties; the
    same *multiplier* gives the same order.
    """
    fast_food = _name_starts_with(FAST_FOOD_PREFIXES)
    low_cuisines = UNHEALTHY_CUISINES | NON_MEAL_CUISINES
    non_meal_chain = _name_starts_with(NON_MEAL_PREFIXES) & ~Q(cuisine__in=low_cuisines)
    # Latest non-blank grade: max of "YYYY-MM-DD" + grade, then its last letter.
    dated_grade = Max(
        Case(
            When(
                ~Q(grade=""),
                then=Concat(Cast("inspection_date", CharField()), "grade"),
            ),
            output_field=CharField(),
        )
    )
    return (
        RestaurantInspection.objects.exclude(dba="")
        .values("camis")
        .annotate(
            name=Max("dba"),
            boro=Max("boro"),
            street=Max("street"),
            zipcode=Max("zipcode"),
            cuisine=Max("cuisine"),
            last_date=Max("inspection_date"),
            dated_grade=dated_grade,
        )
        .annotate(latest_grade=Right("dated_grade", 1))
        .annotate(
            explore_score=Case(
                When(latest_grade="A", then=2),
                When(latest_grade="B", then=1),
                default=0,
                output_field=IntegerField(),
            )
            + Case(
                When(cuisine__in=HEALTHY_CUISINES, then=1),
                When(cuisine__in=low_cuisines, then=-1),
                default=0,
                output_field=IntegerField(),
            )
            + Case(
                When(non_meal_chain, then=-1), default=0, output_field=IntegerField()
            )
            + Case(When(fast_food, then=-2), default=0, output_field=IntegerField()),
            shuffle=Mod(Cast("camis", BigIntegerField()) * multiplier, SHUFFLE_MODULUS),
        )
    )


def _explore_rows():
    """All restaurants for "Explore more", best DB score first. Ties are
    shuffled with a seed that changes daily, so pages stay consistent within a
    day."""
    multiplier = _shuffle_multiplier(_today().isoformat())
    return _scored_restaurants(multiplier).order_by(
        "-explore_score", "shuffle", "camis"
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
    restaurant_rows = _explore_rows()
    if selected_boro in borough_options:
        restaurant_rows = restaurant_rows.filter(boro__iexact=selected_boro)
    else:
        selected_boro = ""
    page_obj = Paginator(restaurant_rows, 16).get_page(request.GET.get("page"))
    restaurants = list(page_obj.object_list)

    # Top 3 picks – only on the first page so paginated browsing stays fast.
    # With a borough selected, the picks come from that borough. Places already
    # shown as Top picks are left out of this page (other pages are unchanged,
    # so paging is stable).
    top_picks = []
    if page_obj.number == 1:
        top_picks = _top_picks(request, count=3, boro=selected_boro)
        shown = {pick["camis"] for pick in top_picks}
        restaurants = [row for row in restaurants if row["camis"] not in shown]
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

    return render(
        request,
        "search/home.html",
        {
            "restaurants": restaurants,
            "page_obj": page_obj,
            "borough_options": borough_options,
            "selected_boro": selected_boro,
            "top_picks": top_picks,
            "personalized_picks": any(pick.get("ai_reason") for pick in top_picks),
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
        feedback=_feedback_prefs(request),
        camis=camis,
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


@login_required
@require_POST
def pick_feedback(request, camis):
    """Save a Like / Not interested on a Top pick; pressing it again undoes it."""
    choice = request.POST.get("value")
    values = {
        "like": RecommendationFeedback.LIKE,
        "not_interested": RecommendationFeedback.NOT_INTERESTED,
    }
    if choice not in values:
        return redirect("search:home")
    latest = (
        RestaurantInspection.objects.filter(camis=camis)
        .order_by("-inspection_date")
        .first()
    )
    if latest is None:
        raise Http404("Restaurant not found")
    existing = RecommendationFeedback.objects.filter(
        user_id=request.user.pk, camis=camis
    ).first()
    if existing is not None and existing.value == values[choice]:
        existing.delete()
    else:
        RecommendationFeedback.objects.update_or_create(
            user_id=request.user.pk,
            camis=camis,
            defaults={
                "value": values[choice],
                "name": latest.dba or "",
                "cuisine": latest.cuisine or "",
            },
        )
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}
    ):
        next_url = reverse("search:home")
    return redirect(next_url)


@require_POST
def refresh_place(request, camis):
    try:
        enrich_camis(camis)
    except PlacesAPIError as exc:
        messages.error(request, f"Could not fetch Google data: {exc}")
    else:
        messages.success(request, "Google data updated.")
    return redirect("search:restaurant_detail", camis=camis)
