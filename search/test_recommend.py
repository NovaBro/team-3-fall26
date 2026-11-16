"""Unit tests for the v3 Top Picks recommendation score."""

from types import SimpleNamespace
from unittest import TestCase

from search.profile_options import (
    parse_allergies,
    parse_foods,
    strong_allergy_cuisines,
)
from search.recommend import (
    CALORIE_WEIGHT,
    DEFAULT_WEIGHTS,
    PERSONAL_WEIGHTS,
    TAG_BUDGET,
    TAG_ALLERGY_CHECK,
    TAG_HIDDEN_GEM,
    TAG_HEALTHY_REVIEWS,
    TAG_LOWER_CALORIE,
    TAG_NEARBY,
    TAG_TOP_RATED,
    TAG_YOUR_FAVORITE,
    _weights,
    classify_reviews,
    has_personal_inputs,
    home_zip_boro,
    is_fast_food,
    rating_score,
    score_restaurant,
)


def profile(**fields):
    base = dict(
        weight_lbs=None,
        height_in=None,
        health_goals=[],
        favorite_foods="",
        disliked_foods="",
        home_address="",
        allergies="",
    )
    base.update(fields)
    return SimpleNamespace(**base)


def personal_part(breakdown):
    return next(p for p in breakdown["parts"] if p["key"] == "personal")


class WeightsTests(TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(DEFAULT_WEIGHTS), 1.0)
        self.assertAlmostEqual(sum(PERSONAL_WEIGHTS), 1.0)
        self.assertEqual(PERSONAL_WEIGHTS, (0.40, 0.20, 0.20, 0.20))

    def test_calorie_weights_renormalize_to_one(self):
        default_cal = _weights(has_calories=True)
        self.assertEqual(len(default_cal), 4)
        self.assertAlmostEqual(sum(default_cal), 1.0)
        self.assertAlmostEqual(default_cal[-1], CALORIE_WEIGHT)
        self.assertEqual(default_cal[:3], (0.45, 0.225, 0.225))
        personal_cal = _weights(personal=True, has_calories=True)
        self.assertEqual(len(personal_cal), 5)
        self.assertAlmostEqual(sum(personal_cal), 1.0)
        # Without calories, still three weights.
        self.assertEqual(_weights(has_calories=False), DEFAULT_WEIGHTS)

    def test_personal_part_only_with_personal_inputs(self):
        self.assertFalse(has_personal_inputs(None))
        self.assertFalse(has_personal_inputs(profile(weight_lbs=150, height_in=68)))
        self.assertTrue(has_personal_inputs(profile(weight_lbs=200, height_in=68)))
        self.assertTrue(has_personal_inputs(profile(health_goals=["low-carb"])))
        self.assertTrue(has_personal_inputs(profile(allergies="Dairy")))
        self.assertFalse(has_personal_inputs(profile(favorite_foods="mushrooms")))


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
    def test_parts_add_up_to_total(self):
        score, tags, breakdown = score_restaurant(
            name="Slice House",
            cuisine="Pizza",
            grade="A",
            google_rating=4.0,
            google_count=100,
            zipcode="11201",
            boro="Brooklyn",
            profile=profile(favorite_foods="Pizza", home_address="Brooklyn 11201"),
            calorie_score=None,
        )
        self.assertEqual(breakdown["mode"], "personal")
        self.assertFalse(breakdown["has_calories"])
        keys = [p["key"] for p in breakdown["parts"]]
        self.assertEqual(keys, ["health", "grade", "rating", "personal"])
        parts_sum = sum(p["points"] for p in breakdown["parts"])
        self.assertAlmostEqual(parts_sum, score, places=5)
        self.assertAlmostEqual(breakdown["total"], score, places=5)
        self.assertEqual(breakdown["tags"], tags)
        self.assertLessEqual(score, 100.0)

    def test_no_profile_keeps_three_parts(self):
        _score, _tags, breakdown = score_restaurant(
            name="Green Spot", cuisine="Salads", grade="A", calorie_score=0.8
        )
        self.assertEqual(breakdown["mode"], "default")
        keys = [p["key"] for p in breakdown["parts"]]
        self.assertEqual(keys, ["health", "grade", "rating", "calories"])
        self.assertAlmostEqual(sum(p["weight"] for p in breakdown["parts"]), 1.0)

    def test_bmi_25_leans_to_lighter_meals_at_half_strength(self):
        heavy = profile(weight_lbs=200, height_in=68)  # BMI 30.4
        kwargs = dict(name="Leaf", cuisine="American", grade="A", profile=heavy)
        _s, _t, light = score_restaurant(ai_goals={"weight-loss": 0.9}, **kwargs)
        part = personal_part(light)
        self.assertAlmostEqual(part["value_0_1"], 0.74)  # 0.5 + 1.2 x 0.5 x 0.4
        self.assertIn(("BMI 25+ leans to lighter meals (half)", "+0.24"), part["steps"])
        self.assertIn("Lighter meals, based on your BMI", light["reasons"])
        _s, _t, heavy_food = score_restaurant(ai_goals={"weight-loss": 0.2}, **kwargs)
        self.assertNotIn("Lighter meals, based on your BMI", heavy_food["reasons"])

    def test_bmi_is_ignored_with_muscle_gain_or_low_bmi(self):
        for user in (
            profile(weight_lbs=200, height_in=68, health_goals=["muscle-gain"]),
            profile(weight_lbs=150, height_in=68, home_address="Queens"),
        ):
            _s, _t, breakdown = score_restaurant(
                name="Leaf",
                cuisine="American",
                grade="A",
                profile=user,
                ai_goals={"weight-loss": 0.9, "muscle-gain": 0.5},
            )
            steps = [label for label, _v in personal_part(breakdown)["steps"]]
            self.assertFalse(any("BMI" in label for label in steps))

    def test_weight_loss_picked_is_not_counted_twice(self):
        user = profile(weight_lbs=200, height_in=68, health_goals=["weight-loss"])
        _s, _t, breakdown = score_restaurant(
            name="Leaf",
            cuisine="American",
            grade="A",
            profile=user,
            ai_goals={"weight-loss": 0.9},
        )
        self.assertAlmostEqual(personal_part(breakdown)["value_0_1"], 0.98)


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


class ProfileHeuristicTests(TestCase):
    def test_allergies_from_labels_and_old_text(self):
        self.assertEqual(parse_allergies("Nuts, Dairy"), ["nuts", "dairy"])
        self.assertEqual(
            parse_allergies("peanuts, shrimp, milk"),
            [
                "nuts",
                "shellfish",
                "dairy",
            ],
        )
        risky = strong_allergy_cuisines(["nuts", "fish"])
        self.assertIn("Thai", risky)
        self.assertIn("Seafood", risky)
        self.assertNotIn("Pizza", strong_allergy_cuisines(["dairy"]))

    def test_old_free_text_foods_are_mapped(self):
        options, unknown = parse_foods("chinese food, korean bbq, Tacos, mushrooms")
        self.assertEqual(
            [o.label for o in options], ["Chinese", "Korean", "BBQ", "Tacos"]
        )
        self.assertEqual(unknown, ["mushrooms"])

    def test_dish_matches_cuisine_or_name(self):
        sushi = parse_foods("Sushi")[0][0]
        self.assertTrue(sushi.matches("Japanese", "TOKYO GRILL"))
        self.assertTrue(sushi.matches("Asian/Asian Fusion", "SUSHI PLACE"))
        self.assertFalse(sushi.matches("Chinese", "GOLDEN DRAGON"))

    def test_home_zip_boro_parsing(self):
        zipcode, boro = home_zip_boro("123 Main St, Brooklyn, NY 11201")
        self.assertEqual(zipcode, "11201")
        self.assertEqual(boro, "Brooklyn")
        zipcode, boro = home_zip_boro("Staten Island apartment")
        self.assertEqual(zipcode, "")
        self.assertEqual(boro, "Staten Island")

    def test_favorite_and_dislike_move_personal_fit(self):
        user = profile(
            favorite_foods="Pizza",
            disliked_foods="Thai",
            home_address="Brooklyn 11201",
        )
        _s, fav_tags, fav = score_restaurant(
            name="Slice House",
            cuisine="Pizza",
            grade="A",
            zipcode="11201",
            boro="Brooklyn",
            profile=user,
            price="$",
        )
        self.assertAlmostEqual(personal_part(fav)["value_0_1"], 0.9)  # .5+.3+.1
        self.assertIn(TAG_YOUR_FAVORITE, fav_tags)
        self.assertIn(TAG_NEARBY, fav_tags)

        _s, _t, disliked = score_restaurant(
            name="Thai Garden", cuisine="Thai", grade="A", profile=user
        )
        self.assertAlmostEqual(personal_part(disliked)["value_0_1"], 0.1)

    def test_health_goals_use_ai_goal_scores(self):
        user = profile(health_goals=["muscle-gain"])
        kwargs = dict(name="Grill", cuisine="American", grade="A", profile=user)
        _s, _t, fits = score_restaurant(ai_goals={"muscle-gain": 0.9}, **kwargs)
        _s, _t, misses = score_restaurant(ai_goals={"muscle-gain": 0.1}, **kwargs)
        self.assertAlmostEqual(personal_part(fits)["value_0_1"], 0.98)
        self.assertAlmostEqual(personal_part(misses)["value_0_1"], 0.02)
        self.assertIn("Fits your goal: Muscle gain", fits["reasons"])

    def test_old_goal_keys_still_count(self):
        user = profile(health_goals=["more-energy", "manage-condition"])
        _s, _t, breakdown = score_restaurant(
            name="Bowl",
            cuisine="Mediterranean",
            grade="A",
            profile=user,
            ai_goals={"balanced-diet": 0.5},
        )
        steps = [label for label, _v in personal_part(breakdown)["steps"]]
        self.assertTrue(any(s.startswith("Goal: Balanced diet") for s in steps))

    def test_mild_allergy_lowers_fit_and_warns(self):
        user = profile(allergies="Dairy")
        _s, _t, breakdown = score_restaurant(
            name="Slice", cuisine="Pizza", grade="A", profile=user
        )
        self.assertAlmostEqual(personal_part(breakdown)["value_0_1"], 0.3)
        self.assertEqual(breakdown["allergy_warnings"], ["Dairy"])


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
        # Priority order, at most 5 tags, and no "Grade A" tag.
        self.assertEqual(
            tags,
            [
                TAG_YOUR_FAVORITE,
                TAG_NEARBY,
                TAG_HEALTHY_REVIEWS,
                TAG_TOP_RATED,
                TAG_BUDGET,
            ],
        )

    def test_goal_tag_allergen_warning_and_hidden_gem(self):
        user = profile(health_goals=["muscle-gain", "low-carb"], allergies="Dairy")
        _s, tags, _ = score_restaurant(
            name="Grill",
            cuisine="Italian",
            grade="A",
            google_rating=4.7,
            google_count=60,
            profile=user,
            ai_goals={"muscle-gain": 0.65, "low-carb": 0.5},
        )
        # Dairy warning first, then both goal tags (best fit first), then
        # Hidden gem (60 reviews, 4.7 stars) instead of Top rated.
        self.assertEqual(
            tags, [TAG_ALLERGY_CHECK, "High protein", "Low carb", TAG_HIDDEN_GEM]
        )

    def test_no_goal_tag_from_cuisine_hint_alone(self):
        _s, tags, _ = score_restaurant(
            name="Leaf",
            cuisine="Salads",  # +0.1 for weight loss, but nothing to read
            grade="A",
            profile=profile(health_goals=["weight-loss"]),
        )
        self.assertNotIn("Lighter meals", tags)

    def test_at_most_two_goal_tags(self):
        goals = ["weight-loss", "heart-health", "balanced-diet", "less-sugar"]
        _s, tags, _ = score_restaurant(
            name="Leaf",
            cuisine="American",
            grade="A",
            profile=profile(health_goals=goals),
            ai_goals={goal: 0.8 for goal in goals},
        )
        goal_tags = {"Lighter meals", "Heart-healthy", "Balanced plates", "Low sugar"}
        self.assertEqual(len([t for t in tags if t in goal_tags]), 2)

    def test_allergen_tag_only_for_people_with_that_allergy(self):
        kwargs = dict(name="Slice", cuisine="Pizza", grade="A")
        _s, with_allergy, _b = score_restaurant(
            profile=profile(allergies="Dairy"), **kwargs
        )
        _s, no_allergy, _b = score_restaurant(
            profile=profile(favorite_foods="Pizza"), **kwargs
        )
        _s, anonymous, _b = score_restaurant(**kwargs)
        self.assertEqual(with_allergy[0], "Allergy check")
        self.assertNotIn("Allergy check", no_allergy)
        self.assertNotIn("Allergy check", anonymous)

    def test_bmi_gives_lighter_meals_tag(self):
        heavy = profile(weight_lbs=200, height_in=68)
        _s, tags, _ = score_restaurant(
            name="Leaf",
            cuisine="American",
            grade="A",
            profile=heavy,
            ai_goals={"weight-loss": 0.8},
        )
        self.assertIn("Lighter meals", tags)
        _s, tags, _ = score_restaurant(
            name="Leaf",
            cuisine="American",
            grade="A",
            profile=heavy,
            ai_goals={"weight-loss": 0.4},
        )
        self.assertNotIn("Lighter meals", tags)

    def test_grade_b_and_c_get_a_tag_too(self):
        for grade in ("B", "C"):
            _score, tags, _ = score_restaurant(name="X", grade=grade)
            self.assertEqual(tags, [f"Grade {grade}"])
        _score, tags, _ = score_restaurant(name="X", grade="Z")
        self.assertEqual(tags, [])
