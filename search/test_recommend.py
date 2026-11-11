"""Unit tests for the v3 Top Picks recommendation score."""

from types import SimpleNamespace
from unittest import TestCase

from restaurants.diet_filters import risky_cuisines
from search.recommend import (
    CALORIE_WEIGHT,
    DEFAULT_WEIGHTS,
    HEALTH_FOCUS_WEIGHTS,
    TAG_BUDGET,
    TAG_GRADE_A,
    TAG_HEALTHY_REVIEWS,
    TAG_LOWER_CALORIE,
    TAG_NEARBY,
    TAG_TOP_RATED,
    TAG_YOUR_FAVORITE,
    _weights,
    allergy_keys_from_text,
    bmi,
    classify_reviews,
    health_focus_weights,
    home_zip_boro,
    is_fast_food,
    rating_score,
    score_restaurant,
)


class WeightsTests(TestCase):
    def test_default_and_health_focus_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(DEFAULT_WEIGHTS), 1.0)
        self.assertAlmostEqual(sum(HEALTH_FOCUS_WEIGHTS), 1.0)

    def test_no_price_weight(self):
        self.assertEqual(len(DEFAULT_WEIGHTS), 3)
        self.assertEqual(len(HEALTH_FOCUS_WEIGHTS), 3)

    def test_calorie_weights_renormalize_to_one(self):
        self.assertAlmostEqual(sum(_weights(has_calories=True)), 1.0)
        heavy = SimpleNamespace(
            weight_lbs=200,
            height_in=68,
            health_goals=[],
        )
        self.assertAlmostEqual(sum(_weights(heavy, has_calories=True)), 1.0)
        default_cal = _weights(has_calories=True)
        self.assertEqual(len(default_cal), 4)
        self.assertAlmostEqual(default_cal[-1], CALORIE_WEIGHT)
        self.assertEqual(default_cal[:3], (0.45, 0.225, 0.225))
        # Without calories, still three weights.
        self.assertEqual(_weights(has_calories=False), DEFAULT_WEIGHTS)


class CalorieScoreTests(TestCase):
    def test_lower_median_beats_higher_when_other_parts_equal(self):
        kwargs = dict(
            name="Chain Spot",
            cuisine="American",
            grade="A",
            google_rating=4.0,
            google_count=100,
            reviews=[],
        )
        low, tags_low, _ = score_restaurant(calorie_score=1.0, **kwargs)
        high, tags_high, _ = score_restaurant(calorie_score=0.0, **kwargs)
        none, _, _ = score_restaurant(calorie_score=None, **kwargs)
        self.assertGreater(low - high, 9)  # ~10 points from the calorie term
        self.assertIn(TAG_LOWER_CALORIE, tags_low)
        self.assertNotIn(TAG_LOWER_CALORIE, tags_high)
        # Unlinked path uses 3 weights (score differs from calorie=0.5 mid-point).
        mid, _, _ = score_restaurant(calorie_score=0.5, **kwargs)
        self.assertNotAlmostEqual(none, mid, places=1)


class BreakdownTests(TestCase):
    def test_breakdown_parts_plus_adjustments_match_total(self):
        profile = SimpleNamespace(
            weight_lbs=150,
            height_in=68,
            health_goals=[],
            favorite_foods="Pizza",
            disliked_foods="",
            home_address="Brooklyn 11201",
            allergies="",
        )
        score, tags, breakdown = score_restaurant(
            name="Slice House",
            cuisine="Pizza",
            grade="A",
            google_rating=4.0,
            google_count=100,
            zipcode="11201",
            boro="Brooklyn",
            profile=profile,
            calorie_score=None,
        )
        self.assertEqual(breakdown["mode"], "default")
        self.assertFalse(breakdown["has_calories"])
        self.assertEqual(len(breakdown["parts"]), 3)
        parts_sum = sum(p["points"] for p in breakdown["parts"])
        self.assertAlmostEqual(parts_sum, breakdown["base_points"], places=5)
        adj_sum = sum(a["delta"] for a in breakdown["adjustments"])
        self.assertAlmostEqual(breakdown["base_points"] + adj_sum, score, places=5)
        self.assertAlmostEqual(breakdown["total"], score, places=5)
        self.assertEqual(breakdown["tags"], tags)

    def test_breakdown_includes_calories_and_health_focus(self):
        profile = SimpleNamespace(
            weight_lbs=200,
            height_in=68,
            health_goals=[],
            favorite_foods="",
            disliked_foods="",
            home_address="",
            allergies="",
        )
        _score, _tags, breakdown = score_restaurant(
            name="Green Spot",
            cuisine="Salads",
            grade="A",
            google_rating=4.0,
            google_count=50,
            profile=profile,
            calorie_score=0.8,
        )
        self.assertEqual(breakdown["mode"], "health_focus")
        self.assertTrue(breakdown["has_calories"])
        keys = [p["key"] for p in breakdown["parts"]]
        self.assertEqual(keys, ["health", "grade", "rating", "calories"])
        self.assertAlmostEqual(sum(p["weight"] for p in breakdown["parts"]), 1.0)


class ReviewCountingTests(TestCase):
    def test_one_review_counts_once_despite_many_healthy_words(self):
        text = "healthy fresh salad grilled steamed organic light vegan nutritious"
        healthy, unhealthy, total = classify_reviews([text])
        self.assertEqual(total, 1)
        self.assertEqual(healthy, 1)
        self.assertEqual(unhealthy, 0)


class FastFoodTests(TestCase):
    def test_detects_known_chains(self):
        self.assertTrue(is_fast_food("Taco Bell"))
        self.assertTrue(is_fast_food("KFC/TACO BELL"))
        self.assertTrue(is_fast_food("CHICK-FIL-A"))
        self.assertTrue(is_fast_food("McDonald's #1234"))

    def test_does_not_flag_unrelated_names(self):
        self.assertFalse(is_fast_food("THE TACO SHOP"))
        self.assertFalse(is_fast_food("Sweetgreen"))
        self.assertFalse(is_fast_food("Chipotle Mexican Grill"))
        self.assertFalse(is_fast_food("Subway"))


class ScoreOrderingTests(TestCase):
    def test_sweetgreen_beats_mcdonalds_by_twenty_plus(self):
        reviews = [{"text": "fresh healthy salad"}] * 3
        sweet, _, _ = score_restaurant(
            name="Sweetgreen",
            cuisine="Salads",
            grade="A",
            google_rating=4.0,
            google_count=200,
            reviews=reviews,
        )
        mcd, _, _ = score_restaurant(
            name="McDonald's",
            cuisine="Hamburgers",
            grade="A",
            google_rating=4.0,
            google_count=200,
            reviews=[{"text": "greasy fried salty"}] * 3,
        )
        self.assertGreaterEqual(sweet - mcd, 20)

    def test_bmi_health_focus_flips_order(self):
        # PDF §5: Green Bowl health ~0.9 / low rating; Taqueria ~0.6 / high rating.
        green_kwargs = dict(
            name="Green Bowl",
            cuisine="Salads",
            grade="A",
            google_rating=3.2,
            google_count=100,
            reviews=[
                {"text": "fresh healthy salad"},
                {"text": "organic light vegan"},
                {"text": "nice place"},
            ],
        )
        taco_kwargs = dict(
            name="Taqueria",
            cuisine="Mexican",
            grade="A",
            google_rating=4.6,
            google_count=400,
            reviews=[
                {"text": "fresh grilled"},
                {"text": "ok food"},
                {"text": "fine"},
            ],
        )
        slim = SimpleNamespace(
            weight_lbs=150,
            height_in=68,
            health_goals=[],
            favorite_foods="",
            disliked_foods="",
            home_address="",
            allergies="",
        )
        heavy = SimpleNamespace(
            weight_lbs=200,
            height_in=68,
            health_goals=[],
            favorite_foods="",
            disliked_foods="",
            home_address="",
            allergies="",
        )
        self.assertAlmostEqual(bmi(150, 68), 22.8, places=1)
        self.assertAlmostEqual(bmi(200, 68), 30.4, places=1)
        self.assertFalse(health_focus_weights(slim))
        self.assertTrue(health_focus_weights(heavy))

        green_slim, _, _ = score_restaurant(profile=slim, **green_kwargs)
        taco_slim, _, _ = score_restaurant(profile=slim, **taco_kwargs)
        green_heavy, _, _ = score_restaurant(profile=heavy, **green_kwargs)
        taco_heavy, _, _ = score_restaurant(profile=heavy, **taco_kwargs)

        self.assertGreater(taco_slim, green_slim)
        self.assertGreater(green_heavy, taco_heavy)

    def test_weight_loss_goal_enables_health_focus(self):
        profile = SimpleNamespace(
            weight_lbs=150,
            height_in=68,
            health_goals=["weight-loss"],
            favorite_foods="",
            disliked_foods="",
            home_address="",
            allergies="",
        )
        self.assertTrue(health_focus_weights(profile))


class ProfileHeuristicTests(TestCase):
    def test_allergy_keys_and_risky_cuisines(self):
        keys = allergy_keys_from_text("peanuts, shellfish")
        self.assertEqual(set(keys), {"nuts", "shellfish"})
        risky = risky_cuisines(keys)
        self.assertIn("Thai", risky)
        self.assertIn("Seafood", risky)

    def test_home_zip_boro_parsing(self):
        zipcode, boro = home_zip_boro("123 Main St, Brooklyn, NY 11201")
        self.assertEqual(zipcode, "11201")
        self.assertEqual(boro, "Brooklyn")
        zipcode, boro = home_zip_boro("Staten Island apartment")
        self.assertEqual(zipcode, "")
        self.assertEqual(boro, "Staten Island")

    def test_favorite_and_dislike_adjustments(self):
        profile = SimpleNamespace(
            weight_lbs=None,
            height_in=None,
            health_goals=[],
            favorite_foods="Pizza",
            disliked_foods="Thai",
            home_address="Brooklyn 11201",
            allergies="",
        )
        fav_score, fav_tags, _ = score_restaurant(
            name="Slice House",
            cuisine="Pizza",
            grade="A",
            google_rating=4.0,
            google_count=100,
            zipcode="11201",
            boro="Brooklyn",
            profile=profile,
            price="$",
        )
        base_score, _, _ = score_restaurant(
            name="Slice House",
            cuisine="Pizza",
            grade="A",
            google_rating=4.0,
            google_count=100,
            zipcode="11201",
            boro="Brooklyn",
            price="$",
        )
        self.assertAlmostEqual(fav_score, base_score + 10 + 5, places=1)
        self.assertIn(TAG_YOUR_FAVORITE, fav_tags)
        self.assertIn(TAG_NEARBY, fav_tags)

        dislike_score, _, _ = score_restaurant(
            name="Thai Garden",
            cuisine="Thai",
            grade="A",
            google_rating=4.0,
            google_count=100,
            profile=profile,
        )
        dislike_base, _, _ = score_restaurant(
            name="Thai Garden",
            cuisine="Thai",
            grade="A",
            google_rating=4.0,
            google_count=100,
        )
        self.assertAlmostEqual(dislike_score, dislike_base - 15, places=1)


class RatingAndTagTests(TestCase):
    def test_in_app_ratings_affect_blend(self):
        low_app = rating_score(4.0, 10, 1.0, 50)
        high_app = rating_score(4.0, 10, 5.0, 50)
        self.assertGreater(high_app, low_app)

    def test_all_tags_shown_in_priority_order(self):
        reviews = [
            {"text": "fresh healthy salad grilled"},
            {"text": "organic light vegan"},
            {"text": "greasy fried"},
        ]
        profile = SimpleNamespace(
            weight_lbs=None,
            height_in=None,
            health_goals=[],
            favorite_foods="Salads",
            disliked_foods="",
            home_address="10003 Manhattan",
            allergies="",
        )
        _score, tags, _ = score_restaurant(
            name="Green Bowl",
            cuisine="Salads",
            grade="A",
            google_rating=4.8,
            google_count=200,
            reviews=reviews,
            price="$",
            zipcode="10003",
            boro="Manhattan",
            profile=profile,
        )
        # Every tag that applies is shown, in priority order (no cap of 3).
        self.assertEqual(
            tags,
            [
                TAG_YOUR_FAVORITE,
                TAG_NEARBY,
                TAG_HEALTHY_REVIEWS,
                TAG_BUDGET,
                TAG_TOP_RATED,
                TAG_GRADE_A,
            ],
        )

    def test_grade_b_and_c_get_a_tag_too(self):
        for grade in ("B", "C"):
            _score, tags, _ = score_restaurant(name="X", grade=grade)
            self.assertEqual(tags, [f"Grade {grade}"])
        _score, tags, _ = score_restaurant(name="X", grade="Z")
        self.assertEqual(tags, [])
