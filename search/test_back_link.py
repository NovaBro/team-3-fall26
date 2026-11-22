"""The detail page's Back link returns to Top picks when opened from there.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_back_link
"""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from search.models import RestaurantInspection
from nycfood.test_utils import ALL_DATABASES


class BackLinkTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        RestaurantInspection.objects.create(
            camis="55",
            dba="LEAF BAR",
            boro="Queens",
            street="2 Main St",
            zipcode="11101",
            cuisine="Salads",
            inspection_date="2024-07-01",
            grade="A",
        )
        self.url = reverse("search:restaurant_detail", args=["55"])

    def get(self, query=""):
        with patch("search.views.find_restaurant_place", return_value=None):
            return self.client.get(self.url + query).content.decode()

    def test_default_goes_back_to_search(self):
        html = self.get()
        self.assertIn('href="/search/">&larr; Back to search</a>', html)

    def test_from_top_picks_goes_back_there(self):
        html = self.get("?from=home")
        self.assertIn('href="/">&larr; Back to Top picks</a>', html)
        self.assertIn('href="/" aria-current="page">Top picks</a>', html)

    def test_keeps_the_borough_and_page(self):
        html = self.get("?from=home&boro=Queens&page=2")
        self.assertIn('href="/?boro=Queens&amp;page=2">&larr; Back to Top picks', html)

    def test_top_picks_links_carry_from_home(self):
        with patch("search.views._top_picks", return_value=[]), patch(
            "search.views.find_restaurant_place", return_value=None
        ):
            html = self.client.get(reverse("search:home")).content.decode()
        self.assertIn('href="/restaurant/55/?from=home"', html)


class SearchHeadlineTests(TestCase):
    databases = ALL_DATABASES

    def test_search_page_headline(self):
        html = self.client.get(reverse("search:index")).content.decode()
        self.assertIn("<h1>Down for a healthy bite?</h1>", html)
        self.assertIn("Find your place, your way", html)
