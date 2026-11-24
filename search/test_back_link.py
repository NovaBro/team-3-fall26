"""The detail page's Back link returns to Top picks when opened from there.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_back_link
"""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from nycfood.test_utils import ALL_DATABASES, make_restaurant


class BackLinkTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        make_restaurant(
            "55",
            "LEAF BAR",
            boro="Queens",
            street="2 Main St",
            zipcode="11101",
            cuisine="Salads",
        )
        self.url = reverse("search:restaurant_detail", args=["55"])

    def get(self, query=""):
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
        with patch("search.views._top_picks", return_value=[]):
            html = self.client.get(reverse("search:home")).content.decode()
        self.assertIn('href="/restaurant/55/?from=home"', html)


class SearchHeadlineTests(TestCase):
    databases = ALL_DATABASES

    def test_search_page_headline(self):
        html = self.client.get(reverse("search:index")).content.decode()
        # The search page is a map app: no big headline above it.
        self.assertNotIn("Something new, every day", html)
        self.assertIn('id="filter-form"', html)
