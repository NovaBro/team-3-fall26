import hashlib
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db.models import (
    Avg,
    BigIntegerField,
    Case,
    Count,
    F,
    IntegerField,
    Max,
    Q,
    When,
)
from django.db.models.functions import Cast, Mod
from django.http import Http404, JsonResponse, QueryDict
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
from django.views.decorators.http import require_POST

from assistant.recommend import personalized_picks
from accounts.checkin import DEFAULT_HEADLINE, picker_context
from community.keys import DOHMH, dohmh_key
from community.models import (
    CommunitySubject,
    PlaceEnrichment,
    PlaceReview,
    ReasonBlurb,
    RecommendationFeedback,
    UserRating,
)
from restaurants.diet_filters import ALLERGY_CHOICES
from restaurants.inspections import _latest, _match, _restaurants_in_zip, google_zip
from restaurants.places import PlacesError, find_restaurant_place
from search import ai_scores, find_food, reason_writer
from search.forms import (
    FARMERS_MARKET,
    GOOGLE,
    GROCERY,
    INSPECTIONS,
    RESTAURANT,
    STORE_TYPE_CHOICES,
    FindFoodForm,
)
from search.goal_fit import menu_nutrients
from search.locations import resolve
from search.models import RestaurantInspection, RestaurantSummary
from search.summary import aggregate_inspections
from search.summary_status import summary_ready
from search.menustat import calorie_score_for_name, top_low_calorie_meals
from search.recommend import (
    FAST_FOOD_PREFIXES,
    HEALTHY_CUISINES,
    NON_MEAL_CUISINES,
    NON_MEAL_PREFIXES,
    UNHEALTHY_CUISINES,
    bmi_weight_loss,
    build_feedback_prefs,
    daily_seed,
    home_zip_boro,
    pick_display_review,
    pick_top,
    score_restaurant,
)
from search.profile_options import (
    name_regex,
    normalize_goals,
    parse_allergies,
    parse_foods,
    strong_allergy_cuisines,
)
from search.services.places import PlacesAPIError, enrich_camis

PAGE_SIZE = 25
# Top picks candidates: the first POOL_SIZE places for a meal in the viewer's
# own ranking (the same list Explore more pages through), one Google lookup
# each. Explore more's first page is drawn from the same places, so its
# lookups come from the cache.
POOL_SIZE = 25
PICKS_TIME_ZONE = ZoneInfo("America/New_York")
MAX_CANDIDATES = 31  # POOL_SIZE + favorite and nearby extras
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


def _food_q(option):
    """Rows matching a profile food choice: its cuisines or a word in the name."""
    q = Q(cuisine__in=option.cuisines) if option.cuisines else Q(camis__in=[])
    if option.words:
        q |= Q(name__iregex=name_regex(option.words))
    return q


def _today():
    return datetime.now(PICKS_TIME_ZONE).date()


def _ai_scores(camis, name="", reviews=()):
    """(AI health score 0–1 or None, {goal: 0-1}) for a restaurant.

    Stored scores are reused; a place without them is scored from the given
    reviews on the spot (see search/ai_scores.py)."""
    texts = [r.get("text", "") if isinstance(r, dict) else r for r in reviews or ()]
    return ai_scores.ai_scores_for(camis, name, texts)


def _goal_nutrients(profile, name):
    """MenuStat nutrient medians for the goal fit; skipped without goals."""
    goals = normalize_goals(getattr(profile, "health_goals", None))
    if not goals and bmi_weight_loss(profile) is None:
        return None
    return menu_nutrients(name)


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


# Gyms and studios with a juice bar are inspected like restaurants, but they are
# not places to eat out, so Top picks skip names with these whole words.
NOT_A_RESTAURANT_NAME = r"\b(FITNESS|GYM|YOGA|PILATES)\b"


def _build_candidate_pool(profile, prefs=None, seed="", boro=""):
    """Top picks candidates: the first POOL_SIZE places for a meal (latest
    grade A, with a ZIP code so Google data can be matched) in the viewer's
    ranking, the same list Explore more shows, plus
    favorites/nearby extras. Places marked not interested and cuisines risky
    for the user's allergies are skipped. With *boro*, every candidate comes
    from that borough."""
    allergies = parse_allergies(getattr(profile, "allergies", "") if profile else "")
    excluded = strong_allergy_cuisines(allergies)
    hidden = prefs.hidden if prefs is not None else set()
    multiplier = _shuffle_multiplier(seed)

    def meal_places(in_boro=boro):
        # The viewer's ranking (as in Explore more), keeping places for a meal
        # with latest grade A (no coffee, bakeries, desserts, gyms).
        rows = (
            _ranked_rows(multiplier, prefs, profile)
            .filter(latest_grade="A")
            .exclude(cuisine__in=NON_MEAL_CUISINES | set(excluded))
            .exclude(_name_starts_with(NON_MEAL_PREFIXES))
            .exclude(name__iregex=NOT_A_RESTAURANT_NAME)
            .exclude(zipcode="")  # no ZIP: Google data can't be matched
        )
        if in_boro:
            rows = rows.filter(boro__iexact=in_boro)
        return rows.order_by(*RANK_ORDER)

    # The first POOL_SIZE places, at most MAX_PER_CUISINE of one cuisine (so a
    # liked cuisine can't fill the list); short of places, the rest refill it.
    base, extra, per_cuisine = [], [], Counter()
    for row in meal_places()[: POOL_SIZE * 8]:
        cuisine = (row.get("cuisine") or "").strip()
        if per_cuisine[cuisine] < MAX_PER_CUISINE:
            base.append(row)
            per_cuisine[cuisine] += 1
            if len(base) == POOL_SIZE:
                break
        else:
            extra.append(row)
    base += extra[: POOL_SIZE - len(base)]
    by_camis = {row["camis"]: row for row in base}

    if profile is not None and len(by_camis) < MAX_CANDIDATES:
        favorites = parse_foods(getattr(profile, "favorite_foods", ""))[0]
        added = 0
        for food in favorites:
            if added >= FAVORITE_EXTRA or len(by_camis) >= MAX_CANDIDATES:
                break
            for row in meal_places().filter(_food_q(food))[: FAVORITE_EXTRA * 3]:
                if row["camis"] in by_camis or row["camis"] in hidden:
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
        picks = _build_candidate_pool(
            profile, prefs, _ranking_seed(request, boro), boro
        )
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

    # Places Google couldn't match have no photo, rating or reviews to back a
    # recommendation, so they are skipped while enough matched places remain
    # (without a Google key, or if Google is down, nothing is matched and all
    # places stay).
    matched = [pick for pick in picks if pick["google"]]
    if len(matched) >= count:
        picks = matched

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
                # No single match for Google's place: keep the restaurant
                # this pick came from, so its card still links to details.
                pick["inspection"] = _latest(camis or pick["camis"])
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
        grade = inspection.get("grade") or ""  # no posted grade = unknown
        pick_name = pick.get("name") or ""
        calorie = calorie_score_for_name(pick_name)
        ai_health, ai_goals = _ai_scores(
            camis_id or pick["camis"], pick.get("name") or "", reviews
        )
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
            ai_health=ai_health,
            ai_goals=ai_goals,
            nutrients=_goal_nutrients(profile, pick_name),
        )
        pick["score"] = score
        pick["reason_tags"] = tags
        pick["calorie_score"] = calorie
        pick["like_bonus"] = breakdown["like_bonus"]
        pick["similar_to"] = breakdown["similar_to"]
        pick["reasons"] = breakdown["reasons"]
        pick["allergy_warnings"] = breakdown["allergy_warnings"]
        pick["feedback"] = feedback_values.get(pick["camis"], 0)

    if ranked_by_claude:
        return picks[:count]  # keep Claude's order
    return pick_top(picks, count)


SHUFFLE_MODULUS = 2_147_483_647  # prime, so each daily multiplier is a new order


def _shuffle_multiplier(seed):
    """A seed-specific multiplier: (camis * multiplier) % prime is a new order."""
    digest = hashlib.sha256(str(seed).encode("utf-8")).hexdigest()
    return 1 + int(digest, 16) % (SHUFFLE_MODULUS - 1)


# No inspection for this long: the place has most likely closed. (DOHMH dates
# new, not yet inspected places 1900-01-01; those are not stale.)
STALE_INSPECTION_DAYS = 730
NOT_YET_INSPECTED = date(1900, 1, 1)


def _scored_restaurants(multiplier):
    """One row per restaurant with a DB-only health score (no Google lookups).

    explore_score: latest grade A +2 / B +1, healthy cuisine +1, unhealthy or
    non-meal cuisine (coffee, desserts, ...) -1, coffee / dessert chain filed
    under another cuisine -1, fast-food chain -2, no inspection in the last
    two years (likely closed) -2. ``shuffle`` orders ties; the same
    *multiplier* gives the same order.
    """
    stale_before = _today() - timedelta(days=STALE_INSPECTION_DAYS)
    fast_food = _name_starts_with(FAST_FOOD_PREFIXES)
    low_cuisines = UNHEALTHY_CUISINES | NON_MEAL_CUISINES
    non_meal_chain = _name_starts_with(NON_MEAL_PREFIXES) & ~Q(cuisine__in=low_cuisines)
    # One row per restaurant, worked out once (search/summary.py) instead of
    # grouping every inspection row on each visit. If that table is missing or
    # empty (e.g. the DB was replaced without migrate), group the inspection
    # rows as before: slower, but the page works (see search/summary_status.py).
    if summary_ready():
        rows = RestaurantSummary.objects.values(
            "camis",
            "name",
            "boro",
            "street",
            "zipcode",
            "cuisine",
            "last_date",
            "latest_grade",
        )
    else:
        rows = aggregate_inspections(RestaurantInspection)
    return rows.annotate(
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
        + Case(When(non_meal_chain, then=-1), default=0, output_field=IntegerField())
        + Case(When(fast_food, then=-2), default=0, output_field=IntegerField())
        + Case(
            When(
                last_date__lt=stale_before,
                last_date__gt=NOT_YET_INSPECTED,
                then=-2,
            ),
            default=0,
            output_field=IntegerField(),
        ),
        shuffle=Mod(Cast("camis", BigIntegerField()) * multiplier, SHUFFLE_MODULUS),
    )


def _ranking_seed(request=None, boro=""):
    """One seed per viewer, day and borough, shared by Top picks and Explore
    more so both read the same ranking."""
    user = getattr(request, "user", None)
    user_id = user.pk if user is not None and user.is_authenticated else None
    return f"{daily_seed(_today(), user_id)}:{(boro or '').casefold()}"


def _ranked_rows(multiplier, prefs=None, profile=None):
    """Every restaurant with ``rank`` (the DB score) and ``order_key``.

    Places marked Not interested are left out. Within one score, places are
    shuffled daily; a place in a cuisine the viewer liked, or matching a
    favorite food, gets its shuffle number divided by TASTE_PULL (twice for
    both), so it tends to come earlier while staying mixed in with the rest.
    Taste never lifts a place above a better score. Order with RANK_ORDER.
    """
    rows = _scored_restaurants(multiplier)
    liked = favorite = None
    if prefs is not None:
        rows = rows.exclude(camis__in=prefs.hidden)
        liked_cuisines = [cuisine for cuisine in prefs.liked if cuisine]
        if liked_cuisines:
            liked = Q(cuisine__in=liked_cuisines)
    foods = parse_foods(getattr(profile, "favorite_foods", ""))[0]
    if foods:
        favorite = Q(camis__in=[])
        for food in foods:
            favorite |= _food_q(food)
    pull = TASTE_PULL
    whens = []
    if liked is not None and favorite is not None:
        whens.append(When(liked & favorite, then=F("shuffle") / (pull * pull)))
    for match in (liked, favorite):
        if match is not None:
            whens.append(When(match, then=F("shuffle") / pull))
    order_key = (
        Case(*whens, default=F("shuffle"), output_field=BigIntegerField())
        if whens
        else F("shuffle")
    )
    return rows.annotate(rank=F("explore_score"), order_key=order_key)


RANK_ORDER = ("-rank", "order_key", "camis")
TASTE_PULL = 3  # liked / favorite places sit about 3x earlier within a score
MAX_PER_CUISINE = 5  # Top picks candidates: at most this many of one cuisine


def _explore_rows(request=None, boro=""):
    """All restaurants for "Explore more", in the viewer's ranking: best DB
    score first; within a score, shuffled with the same daily per-viewer seed
    as Top picks and nudged toward their taste (see ``_ranked_rows``), so
    pages stay put within a day."""
    multiplier = _shuffle_multiplier(_ranking_seed(request, boro))
    prefs = _feedback_prefs(request) if request is not None else None
    profile = _profile_for(request) if request is not None else None
    return _ranked_rows(multiplier, prefs, profile).order_by(*RANK_ORDER)


TOP_PICKS_SESSION_KEY = "top_picks_today"


def _is_first_page(page):
    """True for page 1, a missing page, or one Paginator would turn into 1."""
    try:
        return int(page or 1) <= 1
    except (TypeError, ValueError):
        return True


def home(request):
    selected_boro = request.GET.get("boro", "").strip()
    borough_options = list(
        RestaurantInspection.objects.exclude(boro="")
        .exclude(boro__isnull=True)
        .exclude(boro="0")  # a few inspection rows have no real borough
        .values_list("boro", flat=True)
        .distinct()
        .order_by("boro")
    )
    if selected_boro not in borough_options:
        selected_boro = ""
    restaurant_rows = _explore_rows(request, selected_boro)
    if selected_boro:
        restaurant_rows = restaurant_rows.filter(boro__iexact=selected_boro)
    # Top 3 picks – only on the first page so paginated browsing stays fast.
    # With a borough selected, the picks come from that borough. Today's picks
    # are left out of Explore more on every page, so each page shows 16 cards
    # with no repeats: page 1 remembers them in the session for later pages.
    top_picks = []
    seed = _ranking_seed(request, selected_boro)
    if _is_first_page(request.GET.get("page")):
        top_picks = _top_picks(request, count=3, boro=selected_boro)
        shown = [pick["camis"] for pick in top_picks]
        request.session[TOP_PICKS_SESSION_KEY] = {"seed": seed, "camis": shown}
    else:
        saved = request.session.get(TOP_PICKS_SESSION_KEY) or {}
        shown = saved.get("camis", []) if saved.get("seed") == seed else []
    restaurant_rows = restaurant_rows.exclude(camis__in=shown)
    page_obj = Paginator(restaurant_rows, 16).get_page(request.GET.get("page"))
    restaurants = list(page_obj.object_list)
    liked = set()
    if request.user.is_authenticated:
        liked = set(
            RecommendationFeedback.objects.filter(
                user_id=request.user.pk, value=RecommendationFeedback.LIKE
            ).values_list("camis", flat=True)
        )
    for row in restaurants:
        row["image"] = "search/images/nyc-restaurant.jpg"
        row["liked"] = row["camis"] in liked  # heart under the photo

    # Place searches supplement the CSV fields that are absent, such as a full
    # street address, price level, and Google Maps link. Failed searches leave
    # the underlying CSV card intact.
    # Up to 8 Google lookups at a time (was 4); a page has 16 cards.
    with ThreadPoolExecutor(max_workers=8) as executor:
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
            "picks_date": _today(),
            "personalized_picks": any(pick.get("ai_reason") for pick in top_picks),
            # Banner text, plus today's mood / energy dropdowns when logged in.
            **_checkin_context(request),
        },
    )


def _checkin_context(request):
    if request.user.is_authenticated:
        return {"show_checkin": True, **picker_context(request.user)}
    title, lede = DEFAULT_HEADLINE
    return {"show_checkin": False, "hero_title": title, "hero_lede": lede}


def score_for_camis(camis, latest, place, profile=None, feedback=None):
    """Score one restaurant the way the detail page does.

    ``profile`` and ``feedback`` add the viewer's personal parts; leave them
    None for the general score (used by ``write_reasons``).
    """
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
    # The posted grade comes from the latest *graded* inspection; with none it
    # is unknown (scored like other grades, and no "grade A" reason).
    grade = (
        RestaurantInspection.objects.filter(camis=camis)
        .exclude(grade="")
        .order_by("-inspection_date")
        .values_list("grade", flat=True)
        .first()
        or ""
    ).strip()
    ai_health, ai_goals = _ai_scores(camis, latest.dba or "", reviews)
    return score_restaurant(
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
        profile=profile,
        calorie_score=calorie_score_for_name(latest.dba),
        ai_health=ai_health,
        ai_goals=ai_goals,
        nutrients=_goal_nutrients(profile, latest.dba or ""),
        feedback=feedback,
        camis=camis,
    )


GEMINI_PAUSE_KEY = "gemini-paused"
GEMINI_PAUSE_SECONDS = 600  # after a quota error, stop calling for 10 minutes
GEMINI_MISS_SECONDS = 600  # after a failure for one place, retry it later

logger = logging.getLogger(__name__)


def _reason_blurb(camis, latest=None, place=None):
    """Gemini-written reason paragraph for a restaurant, or "".

    Uses the stored one when there is one. Otherwise, if GEMINI_API_KEY is set,
    asks Gemini once (general reasons only, never the viewer's personal ones),
    stores the answer, and returns it. Any failure returns "" so the page shows
    the plain reason list.
    """
    row = (
        ReasonBlurb.objects.filter(camis=str(camis))
        .values_list("text", "model_name")
        .first()
    )
    if row and reason_writer.is_current(row[1]):
        return row[0]
    if latest is None or not settings.GEMINI_API_KEY:
        return ""  # nothing current, and no way to write one now
    miss_key = f"reason-blurb-miss:{camis}"
    if cache.get(GEMINI_PAUSE_KEY) or cache.get(miss_key):
        return ""
    _, _, general = score_for_camis(camis, latest, place)
    try:
        text = reason_writer.write_blurb(
            latest.dba,
            latest.cuisine,
            general["reasons"],
            reason_writer.live_generate(),
        )
    except reason_writer.RateLimited:
        logger.warning("Gemini quota reached; pausing reason paragraphs.")
        cache.set(GEMINI_PAUSE_KEY, True, GEMINI_PAUSE_SECONDS)
        return ""
    except Exception:
        logger.warning("Gemini reason paragraph failed for %s", camis, exc_info=True)
        cache.set(miss_key, True, GEMINI_MISS_SECONDS)
        return ""
    if not text:
        cache.set(miss_key, True, GEMINI_MISS_SECONDS)
        return ""
    ReasonBlurb.objects.update_or_create(
        camis=str(camis),
        defaults={
            "text": text,
            "facts": " · ".join(general["reasons"]),
            "model_name": reason_writer.model_tag(settings.GEMINI_MODEL),
        },
    )
    return text


def _back_link(request):
    """Where "Back" on a detail page goes: Top picks if we came from there."""
    if request.GET.get("from") != "home":
        return reverse("search:index"), "Back to search", False
    params = {key: request.GET[key] for key in ("boro", "page") if request.GET.get(key)}
    url = reverse("search:home")
    return (f"{url}?{urlencode(params)}" if params else url), "Back to Top picks", True


GOOGLE_MISS_SECONDS = 600  # after a failed fetch, wait before trying again


def _place_for_detail(camis):
    """Stored Google data for a restaurant, fetched once if there is none.

    With GOOGLE_AUTO_FETCH and a Places key, the first visit looks the place
    up on Google and stores it (later visits read the stored row). A failure
    is remembered for 10 minutes and the page shows "No Google data" instead.
    """

    def stored():
        return (
            PlaceEnrichment.objects.filter(camis=camis)
            .prefetch_related("reviews")
            .first()
        )

    place = stored()
    if place is not None:
        return place
    if not (settings.GOOGLE_AUTO_FETCH and settings.GOOGLE_PLACES_API_KEY):
        return None
    miss_key = f"google-place-miss:{camis}"
    if cache.get(miss_key):
        return None
    try:
        enrich_camis(camis)
    except PlacesAPIError:
        logger.warning("Google data fetch failed for %s", camis, exc_info=True)
        cache.set(miss_key, True, GOOGLE_MISS_SECONDS)
        return None
    return stored()


def restaurant_detail(request, camis):
    inspections = RestaurantInspection.objects.filter(camis=camis).order_by(
        "-inspection_date"
    )
    latest = inspections.first()
    if latest is None:
        raise Http404("Restaurant not found")
    place = _place_for_detail(camis)
    menu_picks, menustat_name = top_low_calorie_meals(latest.dba, limit=5)
    back_url, back_label, from_top_picks = _back_link(request)
    healthiness_score, reason_tags, score_breakdown = score_for_camis(
        camis,
        latest,
        place,
        profile=_profile_for(request),
        feedback=_feedback_prefs(request),
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
            "reason_blurb": _reason_blurb(camis, latest, place),
            "back_url": back_url,
            "back_label": back_label,
            "from_top_picks": from_top_picks,
        },
    )


@login_required
@require_POST
def pick_feedback(request, camis):
    """Save a Like / Not interested; pressing it again undoes it.

    Used by the Top picks buttons and the heart on Explore more cards. Likes
    feed the scoring (see FeedbackPrefs in search/recommend.py).
    """
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
        saved = 0
    else:
        saved = values[choice]
        RecommendationFeedback.objects.update_or_create(
            user_id=request.user.pk,
            camis=camis,
            defaults={
                "value": values[choice],
                "name": latest.dba or "",
                "cuisine": latest.cuisine or "",
            },
        )
    if request.headers.get("Accept", "").startswith("application/json"):
        # The heart and the Top picks buttons save in the background (no
        # reload); the new choice shapes Top picks on the next visit.
        return JsonResponse(
            {
                "liked": saved == RecommendationFeedback.LIKE,
                "hidden": saved == RecommendationFeedback.NOT_INTERESTED,
            }
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
