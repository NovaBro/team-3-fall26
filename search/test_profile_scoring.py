"""Profile choices (foods, health goals, allergies) and the Personal fit part.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_profile_scoring
"""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.forms import UserProfileForm
from accounts.models import UserProfile
from search import health_ai, views
from search.goal_fit import goal_fit, goals_fit
from search.models import MenuItem
from search.goal_fit import menu_nutrients
from search.menustat import clear_menustat_cache
from search.test_health_ai import fake_encoder
from nycfood.test_utils import ALL_DATABASES, make_restaurant


class GoalFitTests(SimpleTestCase):
    def test_sources_are_averaged_then_cuisine_hint_added(self):
        fit, steps = goal_fit(
            "low-carb", "Steakhouse", ai_goal=0.6, nutrients={"carbohydrates": 25}
        )
        self.assertAlmostEqual(fit, 0.9)  # (0.6 + 1.0) / 2 + 0.1
        self.assertEqual(steps[-1], ("Cuisine (Steakhouse)", "+0.10"))

    def test_no_source_is_neutral(self):
        fit, steps = goal_fit("muscle-gain", "Donuts")
        self.assertAlmostEqual(fit, 0.4)
        self.assertEqual(steps[0], ("No reviews or menu to read", "0.50"))

    def test_several_goals_are_averaged(self):
        average, details = goals_fit(
            ["less-sugar", "heart-health"],
            "",
            {"less-sugar": 0.8, "heart-health": 0.4},
        )
        self.assertAlmostEqual(average, 0.6)
        self.assertEqual([d[0] for d in details], ["Less sugar", "Heart health"])


class AllScoresTests(SimpleTestCase):
    def test_one_pass_gives_health_and_goal_scores(self):
        health, used, goals = health_ai.all_scores(
            ["Grilled chicken, high protein and lean meat. Nice staff."],
            fake_encoder,
        )
        self.assertIsNotNone(health)
        self.assertGreater(goals["muscle-gain"], 0.5)
        self.assertEqual(health_ai.all_scores(["Parking ok."], fake_encoder)[0], None)


class MenuNutrientTests(TestCase):
    def setUp(self):
        clear_menustat_cache()
        for index, protein in enumerate((30, 35, 40)):
            MenuItem.objects.create(
                menu_item_id=index,
                year=2018,
                restaurant="Protein Place",
                item_name=f"Bowl {index}",
                food_category="Entrees",
                calories=500,
                protein=protein,
            )

    def tearDown(self):
        clear_menustat_cache()

    def test_median_of_latest_meals(self):
        nutrients = menu_nutrients("PROTEIN PLACE")
        self.assertEqual(nutrients["protein"], 35)
        self.assertNotIn("sodium", nutrients)  # no values
        fit, _steps = goal_fit("muscle-gain", nutrients=nutrients)
        self.assertAlmostEqual(fit, 25 / 30)


class ProfileFormTests(TestCase):
    databases = ALL_DATABASES

    def form(self, **data):
        user = User.objects.create_user("u")
        return UserProfileForm(
            data=data, instance=UserProfile.objects.create(user=user)
        )

    def test_picker_keeps_labels(self):
        form = self.form(favorite_foods="sushi, Korean BBQ", allergies=["fish"])
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["favorite_foods"], "Sushi, Korean, BBQ")
        self.assertEqual(form.cleaned_data["allergies"], "Fish")

    def test_unknown_food_is_an_error(self):
        form = self.form(favorite_foods="Sushi, mushrooms")
        self.assertFalse(form.is_valid())
        self.assertIn("mushrooms", form.errors["favorite_foods"][0])

    def test_food_cannot_be_favorite_and_disliked(self):
        form = self.form(favorite_foods="Pizza", disliked_foods="Pizza")
        self.assertFalse(form.is_valid())
        self.assertIn("disliked_foods", form.errors)

    def test_old_values_show_as_choices(self):
        user = User.objects.create_user("old")
        profile = UserProfile.objects.create(
            user=user,
            favorite_foods="chinese food, mushrooms",
            health_goals=["more-energy", "manage-condition"],
            allergies="peanuts",
        )
        form = UserProfileForm(instance=profile)
        self.assertEqual(form.initial["favorite_foods"], "Chinese")
        self.assertEqual(form.initial["health_goals"], ["balanced-diet"])
        self.assertEqual(form.initial["allergies"], ["nuts"])
        html = str(form["favorite_foods"])
        self.assertIn("data-food-picker", html)
        self.assertIn("We couldn’t match: mushrooms", html)
        goals_html = str(form["health_goals"])
        self.assertIn("goal-card", goals_html)
        self.assertEqual(goals_html.count('class="goal-card__icon"'), 6)


class CandidatePoolTests(TestCase):
    databases = ALL_DATABASES

    def add(self, place_id, name, cuisine):
        make_restaurant(
            place_id,
            name,
            boro="Queens",
            street="1 Main St",
            zipcode="11101",
            cuisine=cuisine,
        )

    def test_fish_allergy_leaves_out_seafood_and_sushi(self):
        self.add("1", "OCEAN", "Seafood")
        self.add("2", "TOKYO", "Japanese")
        self.add("3", "GREEN", "Salads")
        user = SimpleNamespace(allergies="Fish", favorite_foods="", home_address="")
        rows = views._build_candidate_pool(user, seed="s")
        self.assertEqual([r["place_id"] for r in rows], ["3"])

    def test_dish_favorite_matches_by_name(self):
        for index in range(30):
            self.add(str(100 + index), f"DINER {index}", "American")
        self.add("9", "RAMEN BAR", "Asian/Asian Fusion")
        user = SimpleNamespace(allergies="", favorite_foods="Ramen", home_address="")
        with patch.object(views, "POOL_SIZE", 3):
            rows = views._build_candidate_pool(user, seed="s")
        self.assertIn("9", [r["place_id"] for r in rows])

    def test_profile_page_saves_choices(self):
        user = User.objects.create_user("p", password="pw")
        self.client.force_login(user)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "action": "save_fixed",
                "favorite_foods": "Sushi, Salad",
                "health_goals": ["low-carb"],
                "allergies": ["dairy", "sesame"],
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.favorite_foods, "Sushi, Salad")
        self.assertEqual(profile.health_goals, ["low-carb"])
        self.assertEqual(profile.allergies, "Dairy, Sesame")

    def test_favorites_do_not_repeat_places(self):
        # A place matching several favorite foods must still appear once.
        for place_id, name in (("21", "TOKYO ONE"), ("22", "RAMEN BAR")):
            make_restaurant(place_id, name, boro="Queens", cuisine="Japanese")
        for foods in ("Japanese", "Ramen", "Sushi, Ramen"):
            user = SimpleNamespace(favorite_foods=foods)
            rows = list(
                views._ranked_rows(7, None, user).values_list("place_id", flat=True)
            )
            self.assertEqual(sorted(rows), ["21", "22"], foods)


class StoredGooglePicksTests(TestCase):
    databases = ALL_DATABASES

    def test_top_picks_use_stored_google_data_without_calls(self):
        for index in range(5):
            make_restaurant(
                str(60 + index),
                f"PLACE {index}",
                boro="Queens",
                cuisine=["Salads", "Thai", "Greek", "Korean", "Vegan"][index],
                rating=4.4,
                rating_count=90,
            )
        with patch("search.views.enrich_place_id") as fetch:
            response = self.client.get(reverse("search:home"))
        fetch.assert_not_called()
        picks = response.context["top_picks"]
        self.assertEqual(len(picks), 3)
        self.assertTrue(all(pick["google"]["rating"] == 4.4 for pick in picks))


class BoroughOptionsTests(TestCase):
    databases = ALL_DATABASES

    def test_places_without_a_borough_are_not_offered(self):
        for place_id, boro in (("71", "Queens"), ("72", "")):
            make_restaurant(
                place_id,
                "X",
                boro=boro,
                street="1 Main St",
                zipcode="11101",
                cuisine="Thai",
            )
        response = self.client.get(reverse("search:home"))
        self.assertEqual(response.context["borough_options"], ["Queens"])
