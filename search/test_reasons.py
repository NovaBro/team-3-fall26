"""'Why this pick' sentences built from the score breakdown."""

from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from community.models import Restaurant
from search.recommend import FeedbackPrefs, explain_reasons, score_restaurant
from nycfood.test_utils import ALL_DATABASES, make_restaurant


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

    def test_fallback_reasons_only_fill_in(self):
        both = explain_reasons([(12.5, "Generic", True), (5.0, "X", False)])
        self.assertEqual(both, ["X", "Generic"])
        plenty = explain_reasons(
            [(12.5, "Generic", True), (5.0, "X", False), (4.0, "Y", False)]
        )
        self.assertEqual(plenty, ["X", "Y"])

    def test_nothing_positive(self):
        self.assertEqual(explain_reasons([(-3.0, "bad", False)]), [])


class ScoreReasonsTests(SimpleTestCase):
    def test_healthy_place_with_ai_score(self):
        _s, _t, breakdown = score_restaurant(
            name="GREEN LEAF",
            cuisine="Salads",
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
            google_rating=4.2,
            google_count=382,
            ai_health=0.56,
        )
        self.assertEqual(breakdown["reasons"], [])

    def test_clear_ai_signal_and_high_rating(self):
        _s, _t, breakdown = score_restaurant(
            name="NIZZA",
            cuisine="Italian",
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

    def test_fast_food_gets_no_reason(self):
        _s, _t, breakdown = score_restaurant(
            name="MCDONALD'S",
            cuisine="Hamburgers",
            google_rating=3.5,
            google_count=900,
        )
        self.assertEqual(breakdown["reasons"], [])

    def test_profile_and_like_reasons(self):
        _s, _t, breakdown = score_restaurant(
            name="TACO SPOT",
            cuisine="Mexican",
            boro="Queens",
            place_id="1",
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

    def test_nothing_stands_out(self):
        _s, _t, breakdown = score_restaurant(name="X", cuisine="Mexican")
        self.assertEqual(breakdown["reasons"], [])


class PickReasonsTests(TestCase):
    databases = ALL_DATABASES

    def test_top_picks_carry_reasons(self):
        make_restaurant(
            "88",
            "GREEN LEAF",
            boro="Queens",
            street="1 Main St",
            zipcode="11101",
            cuisine="Salads",
        )
        page = self.client.get(reverse("search:home"))
        pick = page.context["top_picks"][0]
        self.assertEqual(pick["reasons"][0], "Healthy cuisine (Salads)")


class DetailWhyTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        make_restaurant(
            "99",
            "GREEN LEAF",
            boro="Queens",
            street="1 Main St",
            zipcode="11101",
            cuisine="Salads",
        )

    def test_detail_page_lists_the_reasons(self):
        page = self.client.get(reverse("search:restaurant_detail", args=["99"]))
        html = page.content.decode()
        self.assertTrue(any(t in html for t in ("Why it's a good pick", "What to know", "Why it scores lower")))
        self.assertContains(page, "<li>Healthy cuisine (Salads)</li>", html=True)

    def test_no_section_without_reasons(self):
        Restaurant.objects.filter(place_id="99").update(cuisine="Mexican", rating=None)
        page = self.client.get(reverse("search:restaurant_detail", args=["99"]))
        for title in ("a good pick", "What to know", "scores lower"):
            self.assertNotContains(page, title)
