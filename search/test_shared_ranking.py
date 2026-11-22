"""Top picks and Explore more read one ranking per viewer and day.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_shared_ranking
"""

from collections import Counter
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from community.models import RecommendationFeedback
from search import views
from nycfood.test_utils import ALL_DATABASES, make_restaurant

TODAY = date(2026, 11, 15)


def inspection(place_id, name, cuisine="Salads"):
    return make_restaurant(
        place_id,
        name,
        boro="Queens",
        street="1 Main St",
        zipcode="11101",
        cuisine=cuisine,
    )


@patch("search.views._today", return_value=TODAY)
class SharedRankingTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        for n in range(40):
            inspection(str(7000 + n), f"PLACE {n:02d}")
        inspection("7100", "CORNER COFFEE", cuisine="Coffee/Tea")
        self.anna = User.objects.create_user("anna", password="pw-12345!")
        self.ben = User.objects.create_user("ben", password="pw-12345!")

    def request(self, user=None):
        request = RequestFactory().get("/")
        request.user = user or SimpleNamespace(is_authenticated=False, pk=None)
        return request

    def explore(self, user=None):
        with patch("search.views._profile_for", return_value=None):
            return [row["place_id"] for row in views._explore_rows(self.request(user))]

    def pool(self, user=None):
        request = self.request(user)
        seed = views._ranking_seed(request)
        rows = views._build_candidate_pool(None, None, seed)
        return [row["place_id"] for row in rows]

    def test_candidates_are_the_top_of_the_explore_list(self, _today):
        explore = self.explore(self.anna)
        pool = self.pool(self.anna)
        self.assertEqual(len(pool), views.POOL_SIZE)
        meals = [place_id for place_id in explore if place_id != "7100"]
        self.assertEqual(pool, meals[: views.POOL_SIZE])

    def test_each_viewer_has_their_own_order(self, _today):
        self.assertNotEqual(self.explore(self.anna), self.explore(self.ben))
        self.assertNotEqual(self.pool(self.anna), self.pool(self.ben))
        self.assertEqual(self.explore(self.anna), self.explore(self.anna))

    def test_borough_changes_the_seed(self, _today):
        request = self.request(self.anna)
        self.assertNotEqual(
            views._ranking_seed(request), views._ranking_seed(request, "Queens")
        )


class ExplorePagesTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        for n in range(40):
            inspection(str(8000 + n), f"SPOT {n:02d}")

    def page(self, number=None):
        url = "/" if number is None else f"/?page={number}"
        with patch("search.views._today", return_value=TODAY):
            return self.client.get(url).context

    def test_every_page_has_16_cards_and_no_repeats(self):
        first = self.page()
        picks = {pick["place_id"] for pick in first["top_picks"]}
        self.assertEqual(len(picks), 3)
        page1 = [row["place_id"] for row in first["restaurants"]]
        page2 = [row["place_id"] for row in self.page(2)["restaurants"]]
        self.assertEqual(len(page1), 16)
        self.assertEqual(len(page2), 16)
        self.assertFalse(picks & set(page1 + page2))
        self.assertFalse(set(page1) & set(page2))

    def test_page_two_without_page_one_still_works(self):
        page2 = self.page(2)
        self.assertEqual(len(page2["restaurants"]), 16)
        self.assertEqual(page2["top_picks"], [])


class ClosedPlaceTests(TestCase):
    databases = ALL_DATABASES

    def test_places_google_lists_as_closed_are_not_candidates(self):
        inspection("8100", "OPEN")
        place = inspection("8101", "CLOSED")
        place.business_status = "CLOSED_PERMANENTLY"
        place.save()
        with patch("search.views._today", return_value=TODAY):
            rows = views._build_candidate_pool(None, None, "seed")
        self.assertEqual([row["name"] for row in rows], ["OPEN"])


@patch("search.views._today", return_value=TODAY)
class TasteMixTests(TestCase):
    """A liked cuisine is mixed in, not stacked at the top."""

    databases = ALL_DATABASES

    def setUp(self):
        cuisines = ["Japanese", "Salads", "Mediterranean", "Vegan", "Korean"]
        for n in range(100):
            inspection(str(9000 + n), f"PLACE {n:03d}", cuisine=cuisines[n % 5])
        self.user = User.objects.create_user("mia", password="pw-12345!")
        RecommendationFeedback.objects.create(
            user_id=self.user.pk, place_id="1", cuisine="Japanese", value=1
        )

    def test_explore_mixes_the_liked_cuisine(self, _today):
        request = RequestFactory().get("/")
        request.user = self.user
        with patch("search.views._profile_for", return_value=None):
            rows = list(views._explore_rows(request)[:16])
        japanese = sum(row["cuisine"] == "Japanese" for row in rows)
        self.assertGreater(japanese, 0)
        self.assertLess(japanese, 16)

    def test_candidates_cap_one_cuisine(self, _today):
        prefs = views._feedback_prefs(
            SimpleNamespace(user=self.user)  # same prefs the views build
        )
        pool = views._build_candidate_pool(None, prefs, "seed")
        counts = Counter(row["cuisine"] for row in pool)
        self.assertEqual(len(pool), views.POOL_SIZE)
        self.assertLessEqual(max(counts.values()), views.MAX_PER_CUISINE)
