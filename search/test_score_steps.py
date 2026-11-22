"""Each score part on the detail page opens to show how it was worked out.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_score_steps
"""

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from search.recommend import score_restaurant
from nycfood.test_utils import ALL_DATABASES, make_restaurant


def steps(breakdown, key):
    part = next(p for p in breakdown["parts"] if p["key"] == key)
    return dict(part["steps"])


class ScoreStepsTests(SimpleTestCase):
    def test_health_steps_add_up(self):
        _, _, b = score_restaurant(name="Leaf", cuisine="Salads", ai_health=0.73)
        health = steps(b, "health")
        self.assertEqual(health["Starting point"], "0.50")
        self.assertEqual(health["Cuisine (Salads)"], "+0.20")
        self.assertEqual(health["AI review score 0.73 (MiniLM)"], "+0.23")
        self.assertEqual(health["Health"], "0.93")

    def test_keyword_line_without_ai_score(self):
        _, _, b = score_restaurant(name="Leaf", cuisine="Salads")
        self.assertIn("Review keywords (no AI score yet)", steps(b, "health"))

    def test_health_cap_is_shown(self):
        _, _, b = score_restaurant(
            name="McDonald's", cuisine="Hamburgers", ai_health=0.0
        )
        health = steps(b, "health")
        self.assertIn("Kept between 0 and 1", health)
        self.assertEqual(health["Health"], "0.00")

    def test_rating_steps_show_the_bayesian_sum(self):
        _, _, b = score_restaurant(
            name="X", google_rating=3.8, google_count=20, app_avg=5, app_count=2
        )
        rating = steps(b, "rating")
        self.assertEqual(rating["Google"], "3.8★ (20 reviews)")
        self.assertEqual(rating["Our app"], "5.0★ (2 ratings)")
        adjusted = rating["Adjusted with 20 virtual 4.0★ votes"]
        self.assertEqual(adjusted, "(4.0 × 20 + 3.8 × 20 + 5.0 × 2) ÷ 42 = 3.95★")
        self.assertEqual(rating["Rating"], "(3.95 − 3.0) ÷ 2 = 0.48 (0 to 1)")

    def test_no_ratings(self):
        _, _, b = score_restaurant(name="X")
        rating = steps(b, "rating")
        self.assertEqual(rating["Google"], "no rating")
        self.assertEqual(rating["Our app"], "no ratings yet")


class DetailPageStepsTests(TestCase):
    databases = ALL_DATABASES

    def test_parts_open_to_their_steps(self):
        make_restaurant("5", "LEAF", boro="Queens", cuisine="Salads", rating=None)
        html = self.client.get(
            reverse("search:restaurant_detail", args=["5"])
        ).content.decode()
        self.assertEqual(html.count('<li class="healthiness-score__part">'), 2)
        self.assertIn("<dt>Starting point</dt>", html)
        self.assertNotIn("Inspection grade", html)
        self.assertIn("Adjusted with 20 virtual 4.0★ votes", html)
