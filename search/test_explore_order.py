"""Explore more order: closed and poorly rated places drop; taste counts.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_explore_order
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from community.models import RecommendationFeedback
from search import views
from nycfood.test_utils import ALL_DATABASES, make_restaurant

TODAY = date(2026, 11, 15)


def restaurant(place_id, name, cuisine, **fields):
    return make_restaurant(place_id, name, boro="Queens", cuisine=cuisine, **fields)


@patch("search.views._today", return_value=TODAY)
class ExplorePersonalOrderTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        # A fixed id keeps the daily shuffle (seeded by user and day) the same.
        self.user = User.objects.create_user("kim", password="pw-12345!", id=1)

    def order(self, user=None, profile=None):
        request = RequestFactory().get("/")
        request.user = user or SimpleNamespace(is_authenticated=False, pk=None)
        with patch("search.views._profile_for", return_value=profile):
            return [row["name"] for row in views._explore_rows(request)]

    def test_rating_orders_and_closed_places_are_left_out(self, _today):
        restaurant("1", "LOW RATED", "American", rating=3.2)  # -1
        restaurant("2", "BUSY DINER", "American", rating=4.6)  # +2
        restaurant("3", "NEW SPOT", "American", rating=None)  # 0
        restaurant("4", "SHUT", "American", business_status="CLOSED_PERMANENTLY")
        self.assertEqual(self.order(), ["BUSY DINER", "NEW SPOT", "LOW RATED"])

    def test_liked_cuisine_moves_up_and_hidden_is_left_out(self, _today):
        # Ids picked so DINER comes first by the shuffle alone.
        restaurant("10", "TACO PLACE", "Mexican")
        restaurant("61", "DINER", "American")
        restaurant("12", "SKIPPED", "American")
        RecommendationFeedback.objects.create(
            user_id=self.user.pk, place_id="99", cuisine="Mexican", value=1
        )
        RecommendationFeedback.objects.create(
            user_id=self.user.pk, place_id="12", cuisine="American", value=-1
        )
        names = self.order(self.user)
        self.assertEqual(names[0], "TACO PLACE")
        self.assertNotIn("SKIPPED", names)
        self.assertIn("SKIPPED", self.order())  # others still see it

    def test_favorite_food_moves_up(self, _today):
        restaurant("140", "DINER", "American")  # first by the shuffle alone
        restaurant("100", "RAMEN HOUSE", "Japanese")
        profile = SimpleNamespace(favorite_foods="ramen")
        self.assertEqual(self.order(self.user, profile)[0], "RAMEN HOUSE")
