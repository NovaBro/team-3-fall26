"""The detail page fetches Google data once when none is stored.

Google is never called: ``enrich_place_id`` is replaced with a fake.

    GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_auto_fetch
"""

from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from community.keys import GOOGLE
from community.models import PlaceEnrichment
from search.services.places import PlacesAPIError
from nycfood.test_utils import ALL_DATABASES, make_restaurant


@override_settings(GOOGLE_AUTO_FETCH=True, GOOGLE_PLACES_API_KEY="test-key")
class AutoFetchTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        cache.clear()
        make_restaurant("7", "LEAF BAR", boro="Queens", cuisine="Salads")
        self.url = reverse("search:restaurant_detail", args=["7"])
        self.calls = []

    def fake_enrich(self, place_id):
        self.calls.append(place_id)
        if place_id != "7":
            make_restaurant(place_id)  # what enrich_place_id stores for a new place
        return PlaceEnrichment.objects.create(
            kind=GOOGLE, key=f"google:{place_id}", place_id=place_id, rating=4.6
        )

    def visit(self, enrich, url=None):
        with patch("search.views.enrich_place_id", side_effect=enrich):
            return self.client.get(url or self.url)

    def test_first_visit_fetches_and_stores_then_reuses(self):
        page = self.visit(self.fake_enrich)
        self.assertEqual(page.context["place"].rating, 4.6)
        self.visit(self.fake_enrich)
        self.assertEqual(self.calls, ["7"])

    def test_live_google_result_is_stored_when_opened(self):
        url = reverse("search:restaurant_detail", args=["new-place"])
        page = self.visit(self.fake_enrich, url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(self.calls, ["new-place"])

    def test_unknown_place_404s_when_google_fails(self):
        def broken(place_id):
            raise PlacesAPIError("no match")

        url = reverse("search:restaurant_detail", args=["missing"])
        with self.assertLogs("search.views", level="WARNING"):
            self.assertEqual(self.visit(broken, url).status_code, 404)

    def test_failure_shows_no_data_and_waits(self):
        def broken(place_id):
            self.calls.append(place_id)
            raise PlacesAPIError("no match")

        with self.assertLogs("search.views", level="WARNING"):
            page = self.visit(broken)
        self.assertIsNone(page.context["place"])
        self.visit(broken)  # remembered for 10 minutes -> no second call
        self.assertEqual(self.calls, ["7"])

    def test_off_without_key(self):
        with override_settings(GOOGLE_PLACES_API_KEY=""):
            page = self.visit(self.fake_enrich)
        self.assertIsNone(page.context["place"])
        self.assertEqual(self.calls, [])


class AutoFetchOffInTestsTests(TestCase):
    def test_tests_never_fetch(self):
        self.assertFalse(settings.GOOGLE_AUTO_FETCH)
