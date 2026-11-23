from django.test import TestCase
from django.urls import reverse

from community.models import HealthScore, Restaurant


class PlacePanelTests(TestCase):
    databases = "__all__"

    def test_restaurant_panel_uses_our_data(self):
        Restaurant.objects.create(
            place_id="p1", name="Green Bowl", address="1 Main St", cuisine="Salad",
            latitude=40.7, longitude=-73.9, rating=4.5, rating_count=12,
        )
        HealthScore.objects.create(place_id="p1", score=0.86)
        response = self.client.get(reverse("search:place_panel"), {"key": "google:p1"})
        self.assertContains(response, "Green Bowl")
        self.assertContains(response, ">86</span>", html=False)
        self.assertContains(response, "Directions")

    def test_market_panel_uses_given_name(self):
        response = self.client.get(
            reverse("search:place_panel"),
            {"key": "2026|Union Sq|E 17th", "name": "Union Sq", "category": "farmers_market"},
        )
        self.assertContains(response, "Union Sq")
        self.assertContains(response, "Farmers market")
