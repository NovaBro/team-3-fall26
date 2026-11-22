"""curate_pool keeps the best rated places per borough active, deleting none."""

from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from community.keys import FARMERS_MARKET, GROCERY, farmers_market_key, grocery_key
from community.models import PlaceEnrichment, PlaceReview, Restaurant
from nycfood.test_utils import ALL_DATABASES, make_restaurant
from search.curation import MARKETS, RESTAURANTS, STORES, curate, weighted_rating
from search.find_food import restaurant_rows
from search.models import FarmersMarket, HealthyStore


class WeightedRatingTests(SimpleTestCase):
    def test_many_reviews_beat_a_few_perfect_ones(self):
        few = weighted_rating(5.0, 3, mean=4.2, prior=100)
        many = weighted_rating(4.6, 2000, mean=4.2, prior=100)
        self.assertGreater(many, few)

    def test_unrated_has_no_score(self):
        self.assertIsNone(weighted_rating(None, 0, mean=4.2, prior=100))


class RestaurantCurationTests(TestCase):
    databases = ALL_DATABASES

    def test_caps_each_borough_and_keeps_the_best(self):
        for i, rating in enumerate([4.9, 4.5, 4.1]):
            make_restaurant(f"m{i}", rating=rating, rating_count=500)
        make_restaurant("q0", boro="Queens", rating=4.0, rating_count=500)

        curate(kinds=(RESTAURANTS,), per_borough=2)

        self.assertEqual(
            set(Restaurant.pool.values_list("place_id", flat=True)), {"m0", "m1", "q0"}
        )
        self.assertEqual(Restaurant.objects.count(), 4)  # nothing deleted

    def test_filters_closed_low_rated_and_thin_places(self):
        make_restaurant("ok")
        make_restaurant("closed", business_status="CLOSED_PERMANENTLY")
        make_restaurant("low", rating=3.2)
        make_restaurant("thin", rating_count=5)
        make_restaurant("unrated", rating=None, rating_count=None)

        curate(kinds=(RESTAURANTS,))

        self.assertEqual(
            list(Restaurant.pool.values_list("place_id", flat=True)), ["ok"]
        )

    def test_google_data_survives_and_returns(self):
        make_restaurant("a", rating=4.8, rating_count=900)
        make_restaurant("b", rating=4.0, rating_count=900)
        place = PlaceEnrichment.objects.create(
            kind="restaurant_google", key="google:b", place_id="b"
        )
        PlaceReview.objects.create(place=place, text="Great")

        curate(kinds=(RESTAURANTS,), per_borough=1)
        self.assertFalse(Restaurant.objects.get(place_id="b").active)
        self.assertEqual(PlaceReview.objects.count(), 1)

        curate(kinds=(RESTAURANTS,), per_borough=2)
        self.assertTrue(Restaurant.objects.get(place_id="b").active)

    def test_inactive_places_leave_find_food(self):
        make_restaurant("shown")
        make_restaurant("hidden", active=False)
        names = [row["place_id"] for row in restaurant_rows({})]
        self.assertEqual(names, ["shown"])

    def test_dry_run_changes_nothing(self):
        make_restaurant("low", rating=3.0)
        out = StringIO()
        call_command("curate_pool", "--dry-run", stdout=out)
        self.assertTrue(Restaurant.objects.get(place_id="low").active)
        self.assertIn("restaurants: 0 of 1 active", out.getvalue())


class MarketAndStoreCurationTests(TestCase):
    databases = ALL_DATABASES

    def test_market_rules(self):
        def market(name, year=2026):
            return FarmersMarket.objects.create(
                year=year, market_name=name, borough="Bronx", street_address="1 St"
            )

        good, unrated, bad, closed = (market(n) for n in ("good", "new", "bad", "shut"))
        old = market("old", year=2025)
        for m, rating, count, status in [
            (good, 4.7, 50, "OPERATIONAL"),
            (bad, 2.9, 40, "OPERATIONAL"),
            (closed, 4.5, 40, "CLOSED_PERMANENTLY"),
        ]:
            PlaceEnrichment.objects.create(
                kind=FARMERS_MARKET,
                key=farmers_market_key(m.year, m.market_name, m.street_address),
                rating=rating,
                user_rating_count=count,
                business_status=status,
            )

        curate(kinds=(MARKETS,))

        active = set(FarmersMarket.pool.values_list("market_name", flat=True))
        self.assertEqual(active, {good.market_name, unrated.market_name})
        self.assertFalse(FarmersMarket.objects.get(pk=old.pk).active)

    def test_rated_stores_rank_before_unrated(self):
        rated = HealthyStore.objects.create(
            store_name="Rated", street_address="1 St", borough="Bronx", zip_code="10451"
        )
        HealthyStore.objects.create(
            store_name="Unrated", street_address="2 St", borough="Bronx"
        )
        PlaceEnrichment.objects.create(
            kind=GROCERY,
            key=grocery_key(rated.store_name, rated.street_address, rated.zip_code),
            rating=3.8,
            user_rating_count=12,
        )

        curate(kinds=(STORES,), per_borough=1)

        self.assertEqual(
            list(HealthyStore.pool.values_list("store_name", flat=True)), ["Rated"]
        )
