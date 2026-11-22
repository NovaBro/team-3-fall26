"""'Why this pick' sentences built from the score breakdown."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from search.models import RestaurantInspection
from search.recommend import FeedbackPrefs, explain_reasons, score_restaurant
from nycfood.test_utils import ALL_DATABASES


def profile(**fields):
    values = {
        "favorite_foods": "",
        "disliked_foods": "",
        "home_address": "",
        "health_goals": [],
        "allergies": "",
        "weight_lbs": None,
        "height_in": None,
    }
    values.update(fields)
    return SimpleNamespace(**values)


class ExplainReasonsTests(SimpleTestCase):
    def test_strongest_first_and_at_most_three(self):
        reasons = explain_reasons(
            [
                (3.0, "C", False),
                (12.0, "A", False),
                (0.5, "too small", False),
                (8.0, "B", False),
                (2.0, "D", False),
            ]
        )
        self.assertEqual(reasons, ["A", "B", "C"])

    def test_grade_is_only_a_fallback(self):
        both = explain_reasons([(12.5, "Grade", True), (5.0, "X", False)])
        self.assertEqual(both, ["X", "Grade"])
        plenty = explain_reasons(
            [(12.5, "Grade", True), (5.0, "X", False), (4.0, "Y", False)]
        )
        self.assertEqual(plenty, ["X", "Y"])

    def test_nothing_positive(self):
        self.assertEqual(explain_reasons([(-3.0, "bad", False)]), [])


class ScoreReasonsTests(SimpleTestCase):
    def test_healthy_place_with_ai_score(self):
        _s, _t, breakdown = score_restaurant(
            name="GREEN LEAF",
            cuisine="Salads",
            grade="A",
            google_rating=4.8,
            google_count=500,
            ai_health=0.9,
        )
        self.assertEqual(
            breakdown["reasons"],
            [
                "Reviews describe fresh, healthy food",
                "Healthy cuisine (Salads)",
                "Highly rated (4.8★, 500 reviews)",
            ],
        )
        self.assertEqual(
            breakdown["reason_text"],
            "Reviews describe fresh, healthy food · Healthy cuisine (Salads) · "
            "Highly rated (4.8★, 500 reviews)",
        )

    def test_weak_ai_signal_and_average_rating_get_no_sentence(self):
        _s, _t, breakdown = score_restaurant(
            name="THAI TERMINAL",
            cuisine="Thai",
            grade="A",
            google_rating=4.2,
            google_count=382,
            ai_health=0.56,
        )
        self.assertEqual(breakdown["reasons"], ["NYC health grade A"])

    def test_clear_ai_signal_and_high_rating(self):
        _s, _t, breakdown = score_restaurant(
            name="NIZZA",
            cuisine="Italian",
            grade="A",
            google_rating=4.7,
            google_count=2425,
            ai_health=0.62,
        )
        self.assertEqual(
            breakdown["reasons"],
            [
                "Highly rated (4.7★, 2,425 reviews)",
                "Reviews describe fresh, healthy food",
            ],
        )

    def test_keyword_reviews_get_their_own_sentence(self):
        _s, _t, breakdown = score_restaurant(
            name="X", reviews=[{"text": "fresh healthy salad"}] * 3
        )
        self.assertEqual(breakdown["reasons"], ["Reviews mention healthy dishes"])

    def test_fast_food_falls_back_to_the_grade(self):
        _s, _t, breakdown = score_restaurant(
            name="MCDONALD'S",
            cuisine="Hamburgers",
            grade="A",
            google_rating=3.5,
            google_count=900,
        )
        self.assertEqual(breakdown["reasons"], ["NYC health grade A"])

    def test_profile_and_like_reasons(self):
        _s, _t, breakdown = score_restaurant(
            name="TACO SPOT",
            cuisine="Mexican",
            grade="A",
            boro="Queens",
            camis="1",
            profile=profile(favorite_foods="mexican", home_address="Astoria, Queens"),
            feedback=FeedbackPrefs(liked={"Mexican": [("9", "OLD TAQUERIA")]}),
        )
        self.assertEqual(
            breakdown["reasons"],
            [
                "Matches your favorite food (Mexican)",
                "Near your home",
                "Similar to Old Taqueria, which you liked",
            ],
        )

    def test_grade_b_with_nothing_else(self):
        _s, _t, breakdown = score_restaurant(name="X", cuisine="Mexican", grade="B")
        self.assertEqual(breakdown["reasons"], [])


class PickReasonsTests(TestCase):
    databases = ALL_DATABASES

    def test_top_picks_carry_reasons(self):
        RestaurantInspection.objects.create(
            camis="88",
            dba="GREEN LEAF",
            boro="Queens",
            street="1 Main St",
            zipcode="11101",
            cuisine="Salads",
            inspection_date="2024-07-01",
            grade="A",
        )
        with patch("search.views.find_restaurant_place", return_value=None):
            page = self.client.get(reverse("search:home"))
        pick = page.context["top_picks"][0]
        self.assertEqual(pick["reasons"][0], "Healthy cuisine (Salads)")


class DetailWhyTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        RestaurantInspection.objects.create(
            camis="99",
            dba="GREEN LEAF",
            boro="Queens",
            street="1 Main St",
            zipcode="11101",
            cuisine="Salads",
            inspection_date="2024-07-01",
            grade="A",
        )

    def test_detail_page_lists_the_reasons(self):
        page = self.client.get(reverse("search:restaurant_detail", args=["99"]))
        self.assertContains(page, "Why we recommend it")
        self.assertContains(page, "<li>Healthy cuisine (Salads)</li>", html=True)

    def test_no_section_without_reasons(self):
        RestaurantInspection.objects.filter(camis="99").update(
            cuisine="Mexican", grade="B"
        )
        page = self.client.get(reverse("search:restaurant_detail", args=["99"]))
        self.assertNotContains(page, "Why we recommend it")
