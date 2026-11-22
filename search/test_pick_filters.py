"""Top picks skip gyms, and a missing inspection grade is not treated as A.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_pick_filters
"""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from search import views
from search.models import RestaurantInspection
from search.recommend import score_restaurant
from nycfood.test_utils import ALL_DATABASES


def inspection(camis, dba, grade, day="2024-07-01", cuisine="Salads"):
    return RestaurantInspection.objects.create(
        camis=camis,
        dba=dba,
        boro="Queens",
        street="1 Main St",
        zipcode="11101",
        cuisine=cuisine,
        inspection_date=day,
        grade=grade,
    )


class GymFilterTests(TestCase):
    databases = ALL_DATABASES

    def test_gyms_and_studios_are_not_top_picks(self):
        inspection("1", "INTOXX FITNESS", "A", cuisine="Juice, Smoothies, Fruit Salads")
        inspection("2", "BLUE GYM CAFE", "A")
        inspection("3", "SUNRISE YOGA", "A")
        inspection("4", "CORE PILATES STUDIO", "A")
        inspection("5", "GYMKHANA", "A")  # "GYM" is not a whole word here
        inspection("6", "GREEN LEAF", "A")
        pool = {row["name"] for row in views._build_candidate_pool(None, None, "s")}
        self.assertEqual(pool, {"GYMKHANA", "GREEN LEAF"})


class UnknownGradeTests(TestCase):
    databases = ALL_DATABASES

    def reasons(self, camis):
        with patch("search.views.find_restaurant_place", return_value=None):
            page = self.client.get(reverse("search:restaurant_detail", args=[camis]))
        return page.context["score_breakdown"]

    def test_latest_graded_inspection_counts(self):
        inspection("10", "GREEN LEAF", "A", day="2024-01-01")
        inspection("10", "GREEN LEAF", "", day="2025-06-01")  # pending re-inspection
        breakdown = self.reasons("10")
        self.assertIn("NYC health grade A", breakdown["reasons"])

    def test_never_graded_is_unknown_not_a(self):
        inspection("11", "NEW PLACE", "", day="2025-06-01")
        breakdown = self.reasons("11")
        self.assertNotIn("NYC health grade A", breakdown["reasons"])
        grade_part = next(
            p for p in breakdown["parts"] if p["label"] == "Inspection grade"
        )
        self.assertAlmostEqual(grade_part["value_0_1"], 0.3)

    def test_blank_grade_scores_lower_than_a(self):
        with_a, _, _ = score_restaurant(name="X", cuisine="Salads", grade="A")
        unknown, tags, breakdown = score_restaurant(
            name="X", cuisine="Salads", grade=""
        )
        self.assertLess(unknown, with_a)
        self.assertNotIn("Grade A", tags)
        self.assertNotIn("NYC health grade A", breakdown["reasons"])
