"""The detail page fetches Google data once when none is stored.

Google is never called: ``enrich_camis`` is replaced with a fake.

    GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_auto_fetch
"""

from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from community.keys import DOHMH
from community.models import PlaceEnrichment
from search.models import RestaurantInspection
from search.services.places import PlacesAPIError


@override_settings(GOOGLE_AUTO_FETCH=True, GOOGLE_PLACES_API_KEY="test-key")
class AutoFetchTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        cache.clear()
        RestaurantInspection.objects.create(
            camis="7",
            dba="LEAF BAR",
            boro="Queens",
            street="2 Main St",
            zipcode="11101",
            cuisine="Salads",
            inspection_date="2024-07-01",
            grade="A",
        )
        self.url = reverse("search:restaurant_detail", args=["7"])
        self.calls = []

    def fake_enrich(self, camis):
        self.calls.append(camis)
        return PlaceEnrichment.objects.create(
            kind=DOHMH, key=f"camis:{camis}", camis=camis, rating=4.6
        )

    def visit(self, enrich):
        with patch("search.views.enrich_camis", side_effect=enrich), patch(
            "search.views.find_restaurant_place", return_value=None
        ):
            return self.client.get(self.url)

    def test_first_visit_fetches_and_stores_then_reuses(self):
        page = self.visit(self.fake_enrich)
        self.assertEqual(page.context["place"].rating, 4.6)
        self.visit(self.fake_enrich)
        self.assertEqual(self.calls, ["7"])

    def test_failure_shows_no_data_and_waits(self):
        def broken(camis):
            self.calls.append(camis)
            raise PlacesAPIError("no match")

        with self.assertLogs("search.views", level="WARNING"):
            page = self.visit(broken)
        self.assertIsNone(page.context["place"])
        self.assertContains(page, "No Google data stored yet")
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
