"""Cook-at-home suggestions when mood and energy are both high."""

from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import MoodLog
from accounts.mood import today_ny
from community.keys import FARMERS_MARKET, GROCERY, farmers_market_key, grocery_key
from community.models import PlaceEnrichment
from search.cook_at_home import (
    cook_at_home_picks,
    find_food_cook_url,
    is_cook_at_home_check_in,
    passes_place_quality,
)
from search.models import FarmersMarket, HealthyStore
from nycfood.test_utils import ALL_DATABASES, make_restaurant


def enrich_market(market, rating=4.5, reviews=150):
    PlaceEnrichment.objects.update_or_create(
        kind=FARMERS_MARKET,
        key=farmers_market_key(market.year, market.market_name, market.street_address),
        defaults={
            "rating": rating,
            "user_rating_count": reviews,
            "display_name": market.market_name,
        },
    )


def enrich_store(store, rating=4.5, reviews=150):
    PlaceEnrichment.objects.update_or_create(
        kind=GROCERY,
        key=grocery_key(store.store_name, store.street_address, store.zip_code),
        defaults={
            "rating": rating,
            "user_rating_count": reviews,
            "display_name": store.store_name,
        },
    )


class CookAtHomeGateTests(TestCase):
    def test_none_and_partial_are_false(self):
        self.assertFalse(is_cook_at_home_check_in(None))
        self.assertFalse(
            is_cook_at_home_check_in(SimpleNamespace(mood=4, energy_level=None))
        )
        self.assertFalse(
            is_cook_at_home_check_in(SimpleNamespace(mood=None, energy_level=4))
        )

    def test_boundaries(self):
        self.assertFalse(
            is_cook_at_home_check_in(SimpleNamespace(mood=3, energy_level=4))
        )
        self.assertFalse(
            is_cook_at_home_check_in(SimpleNamespace(mood=4, energy_level=3))
        )
        self.assertTrue(
            is_cook_at_home_check_in(SimpleNamespace(mood=4, energy_level=4))
        )
        self.assertTrue(
            is_cook_at_home_check_in(SimpleNamespace(mood=5, energy_level=5))
        )


class PlaceQualityTests(TestCase):
    def test_thresholds(self):
        self.assertTrue(passes_place_quality(4.0, 100))
        self.assertTrue(passes_place_quality(4.2, 150))
        self.assertFalse(passes_place_quality(3.9, 200))
        self.assertFalse(passes_place_quality(4.5, 99))
        self.assertFalse(passes_place_quality(None, 150))
        self.assertFalse(passes_place_quality(4.5, None))


class CookAtHomePickerTests(TestCase):
    databases = ALL_DATABASES

    @classmethod
    def setUpTestData(cls):
        cls.old = FarmersMarket.objects.create(
            year=2025,
            market_name="Old Year Market",
            borough="Brooklyn",
            street_address="1 Old St",
        )
        cls.monday = FarmersMarket.objects.create(
            year=2026,
            market_name="Brooklyn Monday Market",
            borough="Brooklyn",
            street_address="10 Market St",
            days_of_operation="Monday",
            hours_of_operations="8am-2pm",
        )
        cls.weekend = FarmersMarket.objects.create(
            year=2026,
            market_name="Brooklyn Weekend Market",
            borough="Brooklyn",
            street_address="20 Market St",
            days_of_operation="Saturday-Sunday",
        )
        cls.queens_m = FarmersMarket.objects.create(
            year=2026,
            market_name="Queens Market",
            borough="Queens",
            street_address="30 Market St",
            days_of_operation="Monday-Friday",
        )
        cls.bk_store = HealthyStore.objects.create(
            store_name="Brooklyn Healthy",
            street_address="100 Main St",
            borough="Brooklyn",
            zip_code="11201",
            year_awarded=2022,
        )
        cls.ny_store = HealthyStore.objects.create(
            store_name="Manhattan New York Label",
            street_address="5 Broadway",
            borough="New York",
            zip_code="10040",
            year_awarded=2021,
        )
        cls.queens_s = HealthyStore.objects.create(
            store_name="Queens Healthy",
            street_address="40 Queens Blvd",
            borough="Queens",
            zip_code="11375",
            year_awarded=2020,
        )
        cls.low_stars = FarmersMarket.objects.create(
            year=2026,
            market_name="Low Stars Market",
            borough="Brooklyn",
            street_address="11 Low St",
            days_of_operation="Monday",
        )
        cls.few_reviews = HealthyStore.objects.create(
            store_name="Few Reviews Store",
            street_address="12 Thin St",
            borough="Brooklyn",
            zip_code="11201",
            year_awarded=2019,
        )
        # Eligible enrichments
        for market in (cls.monday, cls.weekend, cls.queens_m):
            enrich_market(market)
        enrich_store(cls.bk_store)
        enrich_store(cls.ny_store)
        enrich_store(cls.queens_s)
        # Below thresholds / no enrichment for old year
        enrich_market(cls.low_stars, rating=3.9, reviews=200)
        enrich_store(cls.few_reviews, rating=4.8, reviews=99)

    def test_borough_filter_markets_and_stores(self):
        picks = cook_at_home_picks(
            "Brooklyn", market_count=5, store_count=5, day=date(2026, 11, 16)
        )
        market_names = {m["name"] for m in picks["markets"]}
        store_names = {s["name"] for s in picks["stores"]}
        self.assertIn("Brooklyn Monday Market", market_names)
        self.assertIn("Brooklyn Weekend Market", market_names)
        self.assertNotIn("Queens Market", market_names)
        self.assertNotIn("Old Year Market", market_names)
        self.assertNotIn("Low Stars Market", market_names)
        self.assertEqual(store_names, {"Brooklyn Healthy"})
        self.assertNotIn("Few Reviews Store", store_names)
        self.assertEqual(picks["stores"][0]["year_awarded"], 2022)

    def test_excludes_missing_and_weak_enrichment(self):
        picks = cook_at_home_picks(
            "Brooklyn", market_count=10, store_count=10, day=date(2026, 11, 16)
        )
        names = {m["name"] for m in picks["markets"]} | {
            s["name"] for s in picks["stores"]
        }
        self.assertNotIn("Old Year Market", names)
        self.assertNotIn("Low Stars Market", names)
        self.assertNotIn("Few Reviews Store", names)

    def test_manhattan_includes_new_york_borough_stores(self):
        picks = cook_at_home_picks(
            "Manhattan", market_count=0, store_count=5, day=date(2026, 11, 16)
        )
        self.assertEqual(
            [s["name"] for s in picks["stores"]], ["Manhattan New York Label"]
        )
        self.assertEqual(picks["stores"][0]["borough"], "Manhattan")

    def test_prefers_markets_open_today(self):
        # 2026-11-16 is a Monday.
        picks = cook_at_home_picks(
            "Brooklyn", market_count=1, store_count=0, day=date(2026, 11, 16)
        )
        self.assertEqual(picks["markets"][0]["name"], "Brooklyn Monday Market")
        self.assertEqual(picks["markets"][0]["hours"], "8am-2pm")

    def test_find_food_url_includes_types_and_area(self):
        url = find_food_cook_url("Brooklyn")
        parsed = urlparse(url)
        self.assertEqual(parsed.path, reverse("search:index"))
        query = parse_qs(parsed.query)
        self.assertEqual(set(query["types"]), {"farmers_market", "grocery"})
        self.assertEqual(query["area"], ["Brooklyn"])


class CookAtHomeHomeViewTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        for place_id, name, cuisine, _day in [
            ("1", "GREEN LEAF", "Salads", "2024-07-04"),
            ("2", "LEAF AND CO", "Salads", "2024-07-03"),
            ("3", "TAQUERIA", "Mexican", "2024-07-02"),
            ("4", "THAI SPOT", "Thai", "2024-07-01"),
        ]:
            make_restaurant(
                place_id,
                name,
                boro="Brooklyn",
                street="1 Main St",
                zipcode="11201",
                cuisine=cuisine,
            )
        self.market = FarmersMarket.objects.create(
            year=2026,
            market_name="Home Test Market",
            borough="Brooklyn",
            street_address="9 Farm St",
            days_of_operation="Monday-Sunday",
        )
        self.store = HealthyStore.objects.create(
            store_name="Home Test Store",
            street_address="8 Shop St",
            borough="Brooklyn",
            zip_code="11201",
            year_awarded=2023,
        )
        enrich_market(self.market)
        enrich_store(self.store)
        self.user = User.objects.create_user("cook", "cook@example.com", "pw-12345!")

    def test_high_mood_and_energy_shows_cook_at_home(self):
        self.client.force_login(self.user)
        MoodLog.objects.create(
            user=self.user, mood=4, energy_level=4, log_date=today_ny()
        )
        response = self.client.get(reverse("search:home"), {"boro": "Brooklyn"})
        self.assertTrue(response.context["cook_at_home"]["show"])
        self.assertContains(response, "Cook at home today")
        self.assertContains(response, "Home Test Market")
        self.assertContains(response, "Home Test Store")
        self.assertContains(response, "Browse markets and healthy stores")
        self.assertIn(
            "types=farmers_market", response.context["cook_at_home"]["find_food_url"]
        )
        self.assertIn(
            "types=grocery", response.context["cook_at_home"]["find_food_url"]
        )
        self.assertIn(
            "area=Brooklyn", response.context["cook_at_home"]["find_food_url"]
        )

    def test_high_mood_with_only_weak_enrichment_shows_cta_empty_lists(self):
        PlaceEnrichment.objects.all().delete()
        enrich_market(self.market, rating=3.5, reviews=50)
        enrich_store(self.store, rating=5.0, reviews=10)
        self.client.force_login(self.user)
        MoodLog.objects.create(
            user=self.user, mood=5, energy_level=5, log_date=today_ny()
        )
        response = self.client.get(reverse("search:home"), {"boro": "Brooklyn"})
        self.assertTrue(response.context["cook_at_home"]["show"])
        self.assertEqual(response.context["cook_at_home"]["markets"], [])
        self.assertEqual(response.context["cook_at_home"]["stores"], [])
        self.assertContains(response, "Browse markets and healthy stores")
        self.assertNotContains(response, "Home Test Market")

    def test_low_mood_hides_cook_at_home(self):
        self.client.force_login(self.user)
        MoodLog.objects.create(
            user=self.user, mood=3, energy_level=5, log_date=today_ny()
        )
        response = self.client.get(reverse("search:home"))
        self.assertFalse(response.context["cook_at_home"]["show"])
        self.assertNotContains(response, "Cook at home today")

    def test_anonymous_hides_cook_at_home(self):
        response = self.client.get(reverse("search:home"))
        self.assertFalse(response.context["cook_at_home"]["show"])
        self.assertNotContains(response, "Cook at home today")
