"""Unit tests for the v4 / ranking-v2 Top Picks recommendation score."""

from types import SimpleNamespace
from unittest import TestCase

from search.profile_options import (
    parse_allergies,
    parse_foods,
    strong_allergy_cuisines,
)
from search.recommend import (
    DEFAULT_WEIGHTS,
    HIGH_HEAVY_PENALTY,
    HIGH_LIGHT_BONUS,
    HIGH_NUTRITION_TILT,
    LINKED_WEIGHTS,
    LOW_COMFORT_BONUS,
    LOW_NUTRITION_TILT,
    PERSONAL_WEIGHTS,
    TAG_ALLERGY_CHECK,
    TAG_BUDGET,
    TAG_CLOSER_ENERGY,
    TAG_COMFORT_MOOD,
    TAG_FITS_ENERGY,
    TAG_HEALTHY_REVIEWS,
    TAG_HIDDEN_GEM,
    TAG_LOWER_CALORIE,
    TAG_MENU_BASED,
    TAG_NEARBY,
    TAG_TOP_RATED,
    TAG_YOUR_FAVORITE,
    UNLINKED_HEALTH_FOCUS_WEIGHTS,
    UNLINKED_WEIGHTS,
    _weights,
    bmi,
    check_in_strictness,
    classify_reviews,
    distance_energy_adjustment,
    has_personal_inputs,
    health_focus_weights,
    home_zip_boro,
    is_fast_food,
    mood_overlay,
    nutrition_confidence,
    prior_health_score,
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
    def test_linked_and_unlinked_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(LINKED_WEIGHTS), 1.0)
        self.assertAlmostEqual(sum(UNLINKED_WEIGHTS), 1.0)
        self.assertAlmostEqual(sum(UNLINKED_HEALTH_FOCUS_WEIGHTS), 1.0)
        self.assertAlmostEqual(sum(DEFAULT_WEIGHTS), 1.0)
        self.assertAlmostEqual(sum(PERSONAL_WEIGHTS), 1.0)
        self.assertEqual(len(PERSONAL_WEIGHTS), 4)
        self.assertAlmostEqual(PERSONAL_WEIGHTS[-1], 0.20)

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
        personal = _weights(personal=True, has_calories=False)
        self.assertEqual(len(personal), 4)
        self.assertAlmostEqual(sum(personal), 1.0)
        linked_personal = _weights(personal=True, has_calories=True)
        self.assertEqual(len(linked_personal), 4)
        self.assertAlmostEqual(sum(linked_personal), 1.0)


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
        self.assertFalse(breakdown["has_menu"])
        self.assertFalse(breakdown["has_calories"])
        self.assertEqual(breakdown["confidence"], "low")
        keys = [p["key"] for p in breakdown["parts"]]
        self.assertEqual(keys, ["health", "grade", "rating", "personal"])
        self.assertEqual(
            [p["section"] for p in breakdown["parts"]],
            ["nutrition", "safety", "rating", "personal"],
        )
        parts_sum = sum(p["points"] for p in breakdown["parts"])
        self.assertAlmostEqual(parts_sum, score, places=5)
        self.assertAlmostEqual(breakdown["total"], score, places=5)
        self.assertEqual(breakdown["tags"], tags)
        self.assertAlmostEqual(
            breakdown["health_estimate"], 100.0 * breakdown["prior_health"], places=5
        )

    def test_breakdown_includes_menu_and_health_focus(self):
        # BMI ≥ 25 alone enables health-focus weights and a Personal fit part.
        user = profile(weight_lbs=200, height_in=68)
        _score, _tags, breakdown = score_restaurant(
            name="Green Spot",
            cuisine="Salads",
            grade="A",
            google_rating=4.0,
            google_count=50,
            profile=user,
            calorie_score=0.8,
            menu_match_kind="exact",
            menu_year=2018,
            meal_count=6,
        )
        self.assertEqual(breakdown["mode"], "personal")
        self.assertTrue(breakdown["health_focus"])
        self.assertTrue(breakdown["has_menu"])
        self.assertEqual(breakdown["confidence"], "medium")  # stale year
        keys = [p["key"] for p in breakdown["parts"]]
        self.assertEqual(keys, ["nutrition", "grade", "rating", "personal"])
        self.assertAlmostEqual(sum(p["weight"] for p in breakdown["parts"]), 1.0)
        self.assertAlmostEqual(breakdown["health_estimate"], 80.0)

    def test_no_profile_keeps_three_parts(self):
        _score, _tags, breakdown = score_restaurant(
            name="Green Spot", cuisine="Salads", grade="A", calorie_score=0.8
        )
        self.assertEqual(breakdown["mode"], "default")
        keys = [p["key"] for p in breakdown["parts"]]
        self.assertEqual(keys, ["nutrition", "grade", "rating"])
        self.assertAlmostEqual(sum(p["weight"] for p in breakdown["parts"]), 1.0)
        self.assertAlmostEqual(breakdown["health_estimate"], 80.0)

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


class PriorHealthTests(TestCase):
    def test_cuisine_and_fast_food_priors_are_soft(self):
        healthy = prior_health_score("Salads", [], "Local Bowl")
        unhealthy = prior_health_score("Hamburgers", [], "Local Burger")
        fast = prior_health_score("Hamburgers", [], "McDonald's")
        self.assertAlmostEqual(healthy, 0.7)
        self.assertAlmostEqual(unhealthy, 0.3)
        self.assertAlmostEqual(fast, 0.1)
        self.assertAlmostEqual(healthy - unhealthy, 0.4)


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
        slim = profile(weight_lbs=150, height_in=68)
        heavy = profile(weight_lbs=200, height_in=68)
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
        user = profile(weight_lbs=150, height_in=68, health_goals=["weight-loss"])
        self.assertTrue(health_focus_weights(user))


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

    def test_strictness_treats_missing_side_as_three(self):
        self.assertEqual(
            check_in_strictness(SimpleNamespace(mood=5, energy_level=None)), 4.0
        )
        self.assertEqual(
            check_in_strictness(SimpleNamespace(mood=None, energy_level=1)), 2.0
        )

    def test_high_strictness_prefers_healthier(self):
        check_in = SimpleNamespace(mood=5, energy_level=5)
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
        salad_base, _, salad_base_bd = score_restaurant(
            name="Green Bowl", cuisine="Salads", grade="A", google_rating=4.0
        )
        burger_base, _, burger_base_bd = score_restaurant(
            name="Burger Spot", cuisine="Hamburgers", grade="A", google_rating=4.0
        )
        salad_tilt = HIGH_NUTRITION_TILT * (
            salad_base_bd["health_estimate"] / 100.0 - 0.5
        )
        burger_tilt = HIGH_NUTRITION_TILT * (
            burger_base_bd["health_estimate"] / 100.0 - 0.5
        )
        self.assertAlmostEqual(
            salad, salad_base + HIGH_LIGHT_BONUS + salad_tilt, places=1
        )
        self.assertAlmostEqual(
            burger, burger_base + HIGH_HEAVY_PENALTY + burger_tilt, places=1
        )
        self.assertIn(TAG_FITS_ENERGY, salad_tags)
        self.assertGreater(salad - burger, salad_base - burger_base)
        self.assertGreater(salad_bd["mood_delta"], burger_bd["mood_delta"])

    def test_low_strictness_boosts_comfort_and_is_laxer(self):
        check_in = SimpleNamespace(mood=1, energy_level=1)
        pizza, tags, breakdown = score_restaurant(
            name="Slice House",
            cuisine="Pizza",
            grade="A",
            google_rating=4.0,
            mood_check_in=check_in,
        )
        base, _, base_bd = score_restaurant(
            name="Slice House", cuisine="Pizza", grade="A", google_rating=4.0
        )
        tilt = LOW_NUTRITION_TILT * (base_bd["health_estimate"] / 100.0 - 0.5)
        self.assertAlmostEqual(pizza, base + LOW_COMFORT_BONUS + tilt, places=1)
        self.assertIn(TAG_COMFORT_MOOD, tags)
        self.assertAlmostEqual(
            breakdown["mood_delta"], LOW_COMFORT_BONUS + tilt, places=1
        )

    def test_high_strictness_tilt_prefers_high_nutrition(self):
        check_in = SimpleNamespace(mood=5, energy_level=4)
        light, _, light_bd = score_restaurant(
            name="Chain Spot",
            grade="A",
            calorie_score=0.9,
            mood_check_in=check_in,
        )
        heavy, _, heavy_bd = score_restaurant(
            name="Chain Spot",
            grade="A",
            calorie_score=0.1,
            mood_check_in=check_in,
        )
        self.assertGreater(light, heavy)
        self.assertGreater(light_bd["mood_delta"], heavy_bd["mood_delta"])
        self.assertTrue(
            any("healthier" in row["label"].lower() for row in light_bd["adjustments"])
        )

    def test_low_strictness_tilt_is_laxer_on_nutrition(self):
        check_in = SimpleNamespace(mood=1, energy_level=2)
        delta_light, *_ = mood_overlay(
            check_in, cuisine="American", name="Diner", nutrition=0.9
        )
        delta_heavy, *_ = mood_overlay(
            check_in, cuisine="American", name="Diner", nutrition=0.1
        )
        # Laxer: high nutrition is not preferred (tilt is negative × centered).
        self.assertLess(delta_light, delta_heavy)

    def test_neutral_check_in_is_noop(self):
        check_in = SimpleNamespace(mood=3, energy_level=3)
        delta, tags, rows, _mi, _dd = mood_overlay(
            check_in, cuisine="Salads", name="Green Bowl", nutrition=0.7
        )
        self.assertEqual(delta, 0.0)
        self.assertEqual(tags, [])
        self.assertEqual(rows, [])


class DistanceEnergyAdjustmentTests(TestCase):
    def test_curves_and_tag(self):
        low_near, tags, _ = distance_energy_adjustment(0.4, 1)
        low_far, _, _ = distance_energy_adjustment(2.0, 1)
        high_near, _, _ = distance_energy_adjustment(0.4, 5)
        high_far, _, _ = distance_energy_adjustment(2.0, 5)
        self.assertGreater(low_near, low_far)
        self.assertGreater(low_near - low_far, 2 * (high_near - high_far))
        self.assertIn(TAG_CLOSER_ENERGY, tags)
        self.assertEqual(distance_energy_adjustment(None, 1)[0], 0.0)
        self.assertEqual(distance_energy_adjustment(0.5, None)[0], 0.0)

    def test_score_restaurant_applies_distance_when_pin_and_check_in(self):
        check_in = SimpleNamespace(mood=3, energy_level=1)
        kwargs = dict(
            name="Same Spot",
            cuisine="American",
            grade="A",
            google_rating=4.0,
            mood_check_in=check_in,
            user_lat=40.7128,
            user_lng=-74.0060,
        )
        # ~0.5 mi north of City Hall
        near, _, near_bd = score_restaurant(
            place_lat=40.7200, place_lng=-74.0060, **kwargs
        )
        # ~2.5 mi north
        far, _, far_bd = score_restaurant(
            place_lat=40.7490, place_lng=-74.0060, **kwargs
        )
        self.assertGreater(near, far)
        self.assertGreater(near_bd["distance_delta"], far_bd["distance_delta"])
        near_score, near_tags, _ = score_restaurant(
            place_lat=40.7200, place_lng=-74.0060, **kwargs
        )
        self.assertIn(TAG_CLOSER_ENERGY, near_tags)
        self.assertGreater(near_score, far)

    def test_no_distance_without_check_in(self):
        near, _, near_bd = score_restaurant(
            name="X",
            grade="A",
            user_lat=40.71,
            user_lng=-74.0,
            place_lat=40.72,
            place_lng=-74.0,
        )
        self.assertIsNone(near_bd["distance_mi"])
        self.assertEqual(near_bd["distance_delta"], 0.0)


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
