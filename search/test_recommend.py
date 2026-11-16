"""Unit tests for the v4 / ranking-v2 Top Picks recommendation score."""

from types import SimpleNamespace
from unittest import TestCase

from restaurants.diet_filters import risky_cuisines
from search.recommend import (
    ENERGY_HEAVY_PENALTY,
    ENERGY_LIGHT_BONUS,
    LINKED_WEIGHTS,
    MOOD_COMFORT_BONUS,
    TAG_BUDGET,
    TAG_COMFORT_MOOD,
    TAG_FITS_ENERGY,
    TAG_GRADE_A,
    TAG_HEALTHY_REVIEWS,
    TAG_LOWER_CALORIE,
    TAG_MENU_BASED,
    TAG_NEARBY,
    TAG_TOP_RATED,
    TAG_YOUR_FAVORITE,
    UNLINKED_HEALTH_FOCUS_WEIGHTS,
    UNLINKED_WEIGHTS,
    _weights,
    allergy_keys_from_text,
    bmi,
    classify_reviews,
    health_focus_weights,
    home_zip_boro,
    is_fast_food,
    mood_energy_adjustment,
    nutrition_confidence,
    prior_health_score,
    rating_score,
    score_restaurant,
)


class WeightsTests(TestCase):
    def test_linked_and_unlinked_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(LINKED_WEIGHTS), 1.0)
        self.assertAlmostEqual(sum(UNLINKED_WEIGHTS), 1.0)
        self.assertAlmostEqual(sum(UNLINKED_HEALTH_FOCUS_WEIGHTS), 1.0)

    def test_no_price_weight(self):
        self.assertEqual(len(LINKED_WEIGHTS), 3)
        self.assertEqual(len(UNLINKED_WEIGHTS), 3)

    def test_weights_switch_on_menu_and_health_focus(self):
        self.assertEqual(_weights(has_calories=False), UNLINKED_WEIGHTS)
        self.assertEqual(_weights(has_calories=True), LINKED_WEIGHTS)
        heavy = SimpleNamespace(
            weight_lbs=200,
            height_in=68,
            health_goals=[],
        )
        self.assertEqual(
            _weights(heavy, has_calories=False), UNLINKED_HEALTH_FOCUS_WEIGHTS
        )
        self.assertAlmostEqual(sum(_weights(heavy, has_calories=True)), 1.0)


class ConfidenceTests(TestCase):
    def test_low_without_menu(self):
        self.assertEqual(nutrition_confidence(has_menu=False), "low")

    def test_high_for_exact_fresh_enough_meals(self):
        self.assertEqual(
            nutrition_confidence(
                has_menu=True,
                match_kind="exact",
                menu_year=2020,
                meal_count=6,
            ),
            "high",
        )

    def test_medium_for_stale_or_weak_or_thin(self):
        self.assertEqual(
            nutrition_confidence(
                has_menu=True,
                match_kind="prefix",
                menu_year=2020,
                meal_count=6,
            ),
            "medium",
        )
        self.assertEqual(
            nutrition_confidence(
                has_menu=True,
                match_kind="exact",
                menu_year=2018,
                meal_count=6,
            ),
            "medium",
        )
        self.assertEqual(
            nutrition_confidence(
                has_menu=True,
                match_kind="exact",
                menu_year=2020,
                meal_count=3,
            ),
            "medium",
        )


class CalorieScoreTests(TestCase):
    def test_lower_median_beats_higher_when_other_parts_equal(self):
        kwargs = dict(
            name="Chain Spot",
            cuisine="American",
            grade="A",
            google_rating=4.0,
            google_count=100,
            reviews=[],
            menu_match_kind="exact",
            menu_year=2020,
            meal_count=6,
        )
        low, tags_low, bd_low = score_restaurant(calorie_score=1.0, **kwargs)
        high, tags_high, _ = score_restaurant(calorie_score=0.0, **kwargs)
        none, _, bd_none = score_restaurant(
            calorie_score=None, name="Chain Spot", grade="A"
        )
        self.assertGreater(low - high, 60)  # ~70 pts from menu nutrition weight
        self.assertIn(TAG_LOWER_CALORIE, tags_low)
        self.assertIn(TAG_MENU_BASED, tags_low)
        self.assertNotIn(TAG_LOWER_CALORIE, tags_high)
        self.assertEqual(bd_low["confidence"], "high")
        self.assertEqual(bd_none["confidence"], "low")
        self.assertAlmostEqual(bd_low["health_estimate"], 100.0)
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
        self.assertFalse(breakdown["has_menu"])
        self.assertEqual(breakdown["confidence"], "low")
        self.assertEqual(len(breakdown["parts"]), 3)
        self.assertEqual(
            [p["section"] for p in breakdown["parts"]],
            ["nutrition", "safety", "rating"],
        )
        parts_sum = sum(p["points"] for p in breakdown["parts"])
        self.assertAlmostEqual(parts_sum, breakdown["base_points"], places=5)
        adj_sum = sum(a["delta"] for a in breakdown["adjustments"])
        self.assertAlmostEqual(breakdown["base_points"] + adj_sum, score, places=5)
        self.assertAlmostEqual(breakdown["total"], score, places=5)
        self.assertEqual(breakdown["tags"], tags)
        self.assertAlmostEqual(
            breakdown["health_estimate"], 100.0 * breakdown["prior_health"], places=5
        )

    def test_breakdown_includes_menu_and_health_focus(self):
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
            menu_match_kind="exact",
            menu_year=2018,
            meal_count=6,
        )
        self.assertEqual(breakdown["mode"], "health_focus")
        self.assertTrue(breakdown["has_menu"])
        self.assertEqual(breakdown["confidence"], "medium")  # stale year
        keys = [p["key"] for p in breakdown["parts"]]
        self.assertEqual(keys, ["nutrition", "safety", "rating"])
        self.assertAlmostEqual(sum(p["weight"] for p in breakdown["parts"]), 1.0)
        self.assertAlmostEqual(breakdown["health_estimate"], 80.0)


class ReviewCountingTests(TestCase):
    def test_one_review_counts_once_despite_many_healthy_words(self):
        text = "healthy fresh salad grilled steamed organic light vegan nutritious"
        healthy, unhealthy, total = classify_reviews([text])
        self.assertEqual(total, 1)
        self.assertEqual(healthy, 1)
        self.assertEqual(unhealthy, 0)


class PriorHealthTests(TestCase):
    def test_cuisine_and_fast_food_priors_are_soft(self):
        healthy = prior_health_score("Salads", [], "Local Bowl")
        unhealthy = prior_health_score("Hamburgers", [], "Local Burger")
        fast = prior_health_score("Hamburgers", [], "McDonald's")
        self.assertAlmostEqual(healthy, 0.6)
        self.assertAlmostEqual(unhealthy, 0.4)
        self.assertAlmostEqual(fast, 0.25)
        self.assertLess(healthy - unhealthy, 0.25)


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

    def test_linked_low_calorie_beats_high_calorie(self):
        kwargs = dict(
            name="Chain",
            cuisine="American",
            grade="A",
            google_rating=4.0,
            google_count=50,
            menu_match_kind="exact",
            menu_year=2020,
            meal_count=6,
        )
        low, _, _ = score_restaurant(calorie_score=0.9, **kwargs)
        high, _, _ = score_restaurant(calorie_score=0.1, **kwargs)
        self.assertGreater(low, high)

    def test_health_focus_raises_nutrition_weight(self):
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

        # Health focus should improve Green's standing relative to the taqueria.
        self.assertGreater(
            (green_heavy - taco_heavy) - (green_slim - taco_slim),
            0,
        )

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


class MoodEnergyAdjustmentTests(TestCase):
    def test_no_check_in_leaves_score_unchanged(self):
        base, _, bd = score_restaurant(
            name="Green Bowl", cuisine="Salads", grade="A", google_rating=4.0
        )
        same, _, same_bd = score_restaurant(
            name="Green Bowl",
            cuisine="Salads",
            grade="A",
            google_rating=4.0,
            mood_check_in=None,
        )
        self.assertAlmostEqual(base, same, places=5)
        self.assertEqual(same_bd["mood_delta"], 0.0)

    def test_low_energy_boosts_light_and_penalizes_heavy(self):
        check_in = SimpleNamespace(mood=3, energy_level=1)
        salad, salad_tags, salad_bd = score_restaurant(
            name="Green Bowl",
            cuisine="Salads",
            grade="A",
            google_rating=4.0,
            mood_check_in=check_in,
        )
        burger, _, burger_bd = score_restaurant(
            name="Burger Spot",
            cuisine="Hamburgers",
            grade="A",
            google_rating=4.0,
            mood_check_in=check_in,
        )
        salad_base, _, _ = score_restaurant(
            name="Green Bowl", cuisine="Salads", grade="A", google_rating=4.0
        )
        burger_base, _, _ = score_restaurant(
            name="Burger Spot", cuisine="Hamburgers", grade="A", google_rating=4.0
        )
        self.assertAlmostEqual(salad, salad_base + ENERGY_LIGHT_BONUS, places=1)
        self.assertAlmostEqual(
            burger, burger_base + ENERGY_HEAVY_PENALTY, places=1
        )
        self.assertIn(TAG_FITS_ENERGY, salad_tags)
        self.assertGreater(salad_bd["mood_delta"], 0)
        self.assertLess(burger_bd["mood_delta"], 0)

    def test_low_mood_boosts_comfort_food(self):
        check_in = SimpleNamespace(mood=1, energy_level=3)
        pizza, tags, breakdown = score_restaurant(
            name="Slice House",
            cuisine="Pizza",
            grade="A",
            google_rating=4.0,
            mood_check_in=check_in,
        )
        base, _, _ = score_restaurant(
            name="Slice House", cuisine="Pizza", grade="A", google_rating=4.0
        )
        self.assertAlmostEqual(pizza, base + MOOD_COMFORT_BONUS, places=1)
        self.assertIn(TAG_COMFORT_MOOD, tags)
        self.assertEqual(breakdown["mood_delta"], MOOD_COMFORT_BONUS)

    def test_low_energy_uses_menu_calorie_signal(self):
        check_in = SimpleNamespace(mood=3, energy_level=2)
        delta, tags, rows = mood_energy_adjustment(
            "American", "Local Diner", check_in, calorie_score=0.9
        )
        self.assertGreater(delta, 0)
        self.assertIn(TAG_FITS_ENERGY, tags)
        self.assertTrue(any("Lower-calorie" in row["label"] for row in rows))

    def test_neutral_check_in_is_noop(self):
        check_in = SimpleNamespace(mood=3, energy_level=3)
        delta, tags, rows = mood_energy_adjustment(
            "Salads", "Green Bowl", check_in
        )
        self.assertEqual(delta, 0.0)
        self.assertEqual(tags, [])
        self.assertEqual(rows, [])


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
