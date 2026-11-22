"""Explore more order: likely-closed places drop; logged-in taste counts.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_explore_order
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from community.models import RecommendationFeedback
from search import views
from search.models import RestaurantInspection
from nycfood.test_utils import ALL_DATABASES

TODAY = date(2026, 11, 15)


def inspection(camis, dba, cuisine, day="2026-06-01", grade="A"):
    return RestaurantInspection.objects.create(
        camis=camis,
        dba=dba,
        boro="Queens",
        street="1 Main St",
        zipcode="11101",
        cuisine=cuisine,
        inspection_date=day,
        grade=grade,
    )


@patch("search.views._today", return_value=TODAY)
class ExplorePersonalOrderTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.user = User.objects.create_user("kim", password="pw-12345!")

    def order(self, user=None, profile=None):
        request = RequestFactory().get("/")
        request.user = user or SimpleNamespace(is_authenticated=False, pk=None)
        with patch("search.views._profile_for", return_value=profile):
            return [row["name"] for row in views._explore_rows(request)]

    def test_place_not_inspected_for_two_years_goes_last(self, _today):
        inspection("1", "OLD SALAD", "Salads", day="2024-01-10")  # 3 - 2
        inspection("2", "BUSY DINER", "American")  # 2
        inspection("3", "NEW SPOT", "American", day="1900-01-01", grade="")  # 0, not -2
        self.assertEqual(self.order(), ["BUSY DINER", "OLD SALAD", "NEW SPOT"])

    def test_liked_cuisine_moves_up_and_hidden_is_left_out(self, _today):
        inspection("10", "TACO PLACE", "Mexican")
        inspection("11", "DINER", "American")
        inspection("12", "SKIPPED", "American")
        RecommendationFeedback.objects.create(
            user_id=self.user.pk, camis="99", cuisine="Mexican", value=1
        )
        RecommendationFeedback.objects.create(
            user_id=self.user.pk, camis="12", cuisine="American", value=-1
        )
        names = self.order(self.user)
        self.assertEqual(names[0], "TACO PLACE")
        self.assertNotIn("SKIPPED", names)
        self.assertIn("SKIPPED", self.order())  # others still see it

    def test_favorite_food_moves_up(self, _today):
        inspection("20", "DINER", "American")
        inspection("21", "RAMEN HOUSE", "Japanese")
        profile = SimpleNamespace(favorite_foods="ramen")
        self.assertEqual(self.order(self.user, profile)[0], "RAMEN HOUSE")
