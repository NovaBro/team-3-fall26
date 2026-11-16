"""The heart on each Explore more card saves a Like (same as Top picks).

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_explore_like
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from community.models import RecommendationFeedback
from search.models import RestaurantInspection


class ExploreLikeTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        RestaurantInspection.objects.create(
            camis="42",
            dba="GREEN LEAF",
            boro="Queens",
            street="1 Main St",
            zipcode="11101",
            cuisine="Salads",
            inspection_date="2024-07-01",
            grade="A",
        )
        self.user = User.objects.create_user("eve", password="pw-12345!")

    def home(self):
        with patch("search.views.find_restaurant_place", return_value=None), patch(
            "search.views._top_picks", return_value=[]
        ):
            return self.client.get(reverse("search:home")).content.decode()

    def test_no_heart_when_logged_out(self):
        self.assertNotIn("restaurant-card__like", self.home())

    def test_heart_shows_and_marks_liked(self):
        self.client.force_login(self.user)
        html = self.home()
        self.assertIn('action="/restaurant/42/feedback/"', html)
        self.assertIn('aria-label="Like"', html)
        RecommendationFeedback.objects.create(
            user_id=self.user.pk, camis="42", value=RecommendationFeedback.LIKE
        )
        html = self.home()
        self.assertIn('aria-label="Liked"', html)
        self.assertIn('aria-pressed="true"', html)

    def test_press_saves_then_undoes_and_returns_to_the_card(self):
        self.client.force_login(self.user)
        url = reverse("search:pick_feedback", args=["42"])
        page = self.client.post(url, {"value": "like", "next": "/?page=2#r-42"})
        self.assertRedirects(page, "/?page=2#r-42", fetch_redirect_response=False)
        saved = RecommendationFeedback.objects.get(user_id=self.user.pk, camis="42")
        self.assertEqual(saved.value, RecommendationFeedback.LIKE)
        self.assertEqual(saved.cuisine, "Salads")
        self.client.post(url, {"value": "like", "next": "/"})
        self.assertFalse(RecommendationFeedback.objects.exists())

    def test_background_save_returns_json(self):
        self.client.force_login(self.user)
        url = reverse("search:pick_feedback", args=["42"])
        page = self.client.post(url, {"value": "like"}, HTTP_ACCEPT="application/json")
        self.assertEqual(page.json(), {"liked": True, "hidden": False})
        self.assertTrue(RecommendationFeedback.objects.filter(camis="42").exists())
        page = self.client.post(url, {"value": "like"}, HTTP_ACCEPT="application/json")
        self.assertEqual(page.json(), {"liked": False, "hidden": False})
        self.assertFalse(RecommendationFeedback.objects.exists())

    def test_page_loads_the_script(self):
        self.client.force_login(self.user)
        self.assertIn("search/explore_like.js", self.home())

    def test_not_interested_in_background_and_undo(self):
        self.client.force_login(self.user)
        url = reverse("search:pick_feedback", args=["42"])
        page = self.client.post(
            url, {"value": "not_interested"}, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(page.json(), {"liked": False, "hidden": True})
        saved = RecommendationFeedback.objects.get(camis="42")
        self.assertEqual(saved.value, RecommendationFeedback.NOT_INTERESTED)
        page = self.client.post(  # Undo
            url, {"value": "not_interested"}, HTTP_ACCEPT="application/json"
        )
        self.assertEqual(page.json(), {"liked": False, "hidden": False})
        self.assertFalse(RecommendationFeedback.objects.exists())

    def test_undo_restores_an_earlier_like(self):
        self.client.force_login(self.user)
        url = reverse("search:pick_feedback", args=["42"])
        accept = {"HTTP_ACCEPT": "application/json"}
        self.client.post(url, {"value": "like"}, **accept)
        self.client.post(url, {"value": "not_interested"}, **accept)
        page = self.client.post(url, {"value": "like"}, **accept)  # Undo
        self.assertEqual(page.json(), {"liked": True, "hidden": False})
