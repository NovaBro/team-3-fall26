"""Top picks skip gyms and poorly rated places; scores have no grade part.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_pick_filters
"""

from django.test import SimpleTestCase, TestCase

from search import views
from search.recommend import score_restaurant
from nycfood.test_utils import ALL_DATABASES, make_restaurant


def restaurant(place_id, name, cuisine="Salads", **fields):
    return make_restaurant(place_id, name, boro="Queens", cuisine=cuisine, **fields)


class GymFilterTests(TestCase):
    databases = ALL_DATABASES

    def test_gyms_and_studios_are_not_top_picks(self):
        restaurant("1", "INTOXX FITNESS", cuisine="Juice, Smoothies, Fruit Salads")
        restaurant("2", "BLUE GYM CAFE")
        restaurant("3", "SUNRISE YOGA")
        restaurant("4", "CORE PILATES STUDIO")
        restaurant("5", "GYMKHANA")  # "GYM" is not a whole word here
        restaurant("6", "GREEN LEAF")
        pool = {row["name"] for row in views._build_candidate_pool(None, None, "s")}
        self.assertEqual(pool, {"GYMKHANA", "GREEN LEAF"})


class RatingFilterTests(TestCase):
    databases = ALL_DATABASES

    def test_poorly_rated_places_are_not_top_picks(self):
        restaurant("1", "GOOD", rating=4.2)
        restaurant("2", "UNRATED", rating=None, rating_count=None)
        restaurant("3", "BAD", rating=3.1)
        pool = {row["name"] for row in views._build_candidate_pool(None, None, "s")}
        self.assertEqual(pool, {"GOOD", "UNRATED"})


class NoGradeTests(SimpleTestCase):
    def test_score_has_health_and_rating_parts_only(self):
        _score, tags, breakdown = score_restaurant(name="X", cuisine="Salads")
        self.assertEqual(
            [part["key"] for part in breakdown["parts"]], ["health", "rating"]
        )
        self.assertAlmostEqual(sum(p["weight"] for p in breakdown["parts"]), 1.0)
        self.assertFalse(any(tag.startswith("Grade") for tag in tags))
