"""Cheap Top Picks rerank after mood/energy check-in."""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from accounts.checkin import save_today
from search.recommend import mood_overlay, pick_top
from search.views import (
    _apply_mood_overlay_to_pool,
    _ranking_seed,
    _store_top_picks_pool,
)
from nycfood.test_utils import ALL_DATABASES

User = get_user_model()


def _candidate(camis, name, cuisine, nutrition, base_score, *, calorie_score=None):
    return {
        "camis": camis,
        "name": name,
        "cuisine": cuisine,
        "street": "1 Main",
        "boro": "Manhattan",
        "zipcode": "10001",
        "google": {
            "rating": 4.5,
            "rating_count": 100,
            "price": "$$",
            "address": "1 Main",
        },
        "photo_url": "",
        "image": "search/images/nyc-restaurant.jpg",
        "inspection": {"camis": camis, "grade": "A", "date": None},
        "review": None,
        "base_score": base_score,
        "base_reason_tags": ["Grade A"],
        "nutrition": nutrition,
        "calorie_score": calorie_score,
        "place_lat": None,
        "place_lng": None,
        "like_bonus": 0,
        "confidence": 0.5,
        "health_estimate": 100.0 * nutrition,
        "google_rating": 4.5,
        "similar_to": "",
        "reasons": [],
        "allergy_warnings": [],
        "feedback": 0,
        "score": base_score,
        "reason_tags": ["Grade A"],
    }


class MoodOverlayRerankUnitTests(TestCase):
    def test_high_strictness_reorders_toward_healthier(self):
        pool = [
            _candidate("1", "Burger Spot", "Hamburgers", 0.2, 70.0),
            _candidate("2", "Green Bowl", "Salads", 0.85, 68.0),
        ]
        low = SimpleNamespace(mood=1, energy_level=1)
        high = SimpleNamespace(mood=5, energy_level=5)
        low_order = [
            p["camis"] for p in pick_top(_apply_mood_overlay_to_pool(pool, low), 2)
        ]
        high_order = [
            p["camis"] for p in pick_top(_apply_mood_overlay_to_pool(pool, high), 2)
        ]
        self.assertEqual(high_order[0], "2")
        self.assertNotEqual(low_order[0], high_order[0])

    def test_overlay_helper_matches_direct_call(self):
        check_in = SimpleNamespace(mood=5, energy_level=5)
        pick = _candidate("2", "Green Bowl", "Salads", 0.9, 50.0, calorie_score=0.9)
        delta, *_ = mood_overlay(
            check_in,
            cuisine="Salads",
            name="Green Bowl",
            nutrition=0.9,
            calorie_score=0.9,
        )
        scored = _apply_mood_overlay_to_pool([pick], check_in)[0]
        self.assertAlmostEqual(scored["score"], pick["base_score"] + delta, places=5)


class RerankEndpointTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user("reranker", "r@example.com", "pass12345")
        self.client.force_login(self.user)
        self.factory = RequestFactory()
        self.pool = [
            _candidate("1", "Burger Spot", "Hamburgers", 0.2, 72.0),
            _candidate("2", "Green Bowl", "Salads", 0.9, 70.0),
            _candidate("3", "Pizza Place", "Pizza", 0.35, 71.0),
        ]

    def _seed_pool(self, boro=""):
        request = self.factory.get("/")
        request.user = self.user
        seed = _ranking_seed(request, boro)
        _store_top_picks_pool(self.user.pk, boro, seed, self.pool)
        return seed

    def test_rerank_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("search:rerank_top_picks"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    @patch("search.views.find_restaurant_place")
    def test_rerank_uses_cache_without_google(self, find_place):
        self._seed_pool()
        save_today(self.user, "mood", 5)
        save_today(self.user, "energy", 5)
        response = self.client.get(reverse("search:rerank_top_picks"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("html", payload)
        self.assertIn("Green Bowl", payload["html"])
        self.assertIn("mood and energy", payload["subtitle"])
        find_place.assert_not_called()

    @patch("search.views.find_restaurant_place")
    def test_rerank_order_changes_with_mood(self, find_place):
        self._seed_pool()
        save_today(self.user, "mood", 1)
        save_today(self.user, "energy", 1)
        low = self.client.get(reverse("search:rerank_top_picks")).json()["html"]
        save_today(self.user, "mood", 5)
        save_today(self.user, "energy", 5)
        high = self.client.get(reverse("search:rerank_top_picks")).json()["html"]
        self.assertNotEqual(low, high)
        self.assertLess(high.index("Green Bowl"), high.index("Burger Spot"))
        find_place.assert_not_called()

    @patch("search.views.find_restaurant_place")
    @patch("search.views._top_picks")
    def test_rerank_rebuilds_pool_on_cache_miss(self, top_picks, find_place):
        def populate(request, count=3, boro=""):
            seed = _ranking_seed(request, boro)
            _store_top_picks_pool(self.user.pk, boro, seed, self.pool)
            return pick_top(self.pool, count)

        top_picks.side_effect = populate
        response = self.client.get(reverse("search:rerank_top_picks"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("html", response.json())
        top_picks.assert_called_once()
        find_place.assert_not_called()
