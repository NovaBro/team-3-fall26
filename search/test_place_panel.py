from django.test import TestCase
from django.urls import reverse

from community.models import HealthScore, Restaurant


class PlacePanelTests(TestCase):
    databases = "__all__"

    def test_restaurant_panel_uses_our_data(self):
        Restaurant.objects.create(
            place_id="p1",
            name="Green Bowl",
            address="1 Main St",
            cuisine="Salad",
            latitude=40.7,
            longitude=-73.9,
            rating=4.5,
            rating_count=12,
        )
        HealthScore.objects.create(place_id="p1", score=0.86)
        response = self.client.get(reverse("search:place_panel"), {"key": "google:p1"})
        self.assertContains(response, "Green Bowl")
        self.assertContains(response, ">86</span>", html=False)
        self.assertContains(response, "Directions")

    def test_market_panel_uses_given_name(self):
        response = self.client.get(
            reverse("search:place_panel"),
            {
                "key": "2026|Union Sq|E 17th",
                "name": "Union Sq",
                "category": "farmers_market",
            },
        )
        self.assertContains(response, "Union Sq")
        self.assertContains(response, "Farmers market")


class TopPicksHealthMatchesPanelTests(TestCase):
    """The Health+ number on a Top pick is the same one its Search panel shows."""

    databases = "__all__"

    def test_top_pick_health_is_the_stored_ai_score(self):
        from nycfood.test_utils import make_restaurant

        for i, cuisine in enumerate(["American", "Thai", "Mexican"]):
            make_restaurant(f"p{i}", name=f"Place {i}", cuisine=cuisine)
            HealthScore.objects.create(place_id=f"p{i}", score=0.31 + i / 10)
        picks = self.client.get(reverse("search:home")).context["top_picks"]
        self.assertTrue(picks)
        for pick in picks:
            panel = self.client.get(
                reverse("search:place_panel"), {"key": f"google:{pick['place_id']}"}
            )
            self.assertEqual(panel.context["health"], pick["health"])
