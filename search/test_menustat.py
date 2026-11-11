"""Tests for MenuStat matching, meal filters, and calorie helpers."""

from django.test import TestCase
from django.urls import reverse

from search.menustat import (
    calorie_score_for_name,
    calorie_score_from_median,
    clear_menustat_cache,
    match_menustat_restaurant,
    median_meal_calories,
    qualifying_meals,
    top_low_calorie_meals,
)
from search.models import MenuItem, RestaurantInspection


def _meal(**kwargs):
    defaults = dict(
        menu_item_id="1",
        year=2018,
        restaurant="Test Chain",
        restaurant_id="tc1",
        item_name="Item",
        food_category="Entrees",
        calories=400.0,
        protein=20.0,
        kids_meal=False,
    )
    defaults.update(kwargs)
    return MenuItem.objects.create(**defaults)


class MenuStatHelperTests(TestCase):
    def setUp(self):
        clear_menustat_cache()

    def tearDown(self):
        clear_menustat_cache()

    def test_filters_exclude_drinks_kids_and_low_protein(self):
        _meal(menu_item_id="a", item_name="Grilled Chicken", calories=350, protein=25)
        _meal(
            menu_item_id="b",
            item_name="Diet Coke",
            food_category="Beverages",
            calories=0,
            protein=0,
        )
        _meal(
            menu_item_id="c",
            item_name="Kids Nuggets",
            calories=300,
            protein=18,
            kids_meal=True,
        )
        _meal(
            menu_item_id="d",
            item_name="Side Salad",
            food_category="Salads",
            calories=120,
            protein=5,
        )
        _meal(
            menu_item_id="e",
            item_name="Old Burger",
            year=2017,
            food_category="Burgers",
            calories=500,
            protein=20,
        )
        meals = qualifying_meals("Test Chain")
        names = {m.item_name for m in meals}
        self.assertEqual(names, {"Grilled Chicken"})
        self.assertEqual(median_meal_calories("Test Chain"), None)  # need ≥3

    def test_median_and_top5_use_latest_year(self):
        for i, cal in enumerate([300, 400, 500, 600], start=1):
            _meal(
                menu_item_id=f"n{i}",
                item_name=f"Meal {i}",
                calories=float(cal),
                protein=20,
            )
        _meal(
            menu_item_id="old",
            item_name="Ancient Salad",
            year=2015,
            food_category="Salads",
            calories=100,
            protein=20,
        )
        self.assertEqual(median_meal_calories("Test Chain"), 450.0)
        top, matched = top_low_calorie_meals("Test Chain", limit=5)
        self.assertEqual(matched, "Test Chain")
        self.assertEqual(
            [m.item_name for m in top], ["Meal 1", "Meal 2", "Meal 3", "Meal 4"]
        )

    def test_fuzzy_match_exact_and_prefix(self):
        _meal(restaurant="McDonald's")
        clear_menustat_cache()
        self.assertEqual(match_menustat_restaurant("McDonald's"), "McDonald's")
        self.assertEqual(match_menustat_restaurant("McDonald's Midtown"), "McDonald's")
        self.assertIsNone(match_menustat_restaurant("Joe's Pizza Shop"))

    def test_calorie_score_map_endpoints(self):
        self.assertAlmostEqual(calorie_score_from_median(200), 1.0)
        self.assertAlmostEqual(calorie_score_from_median(800), 0.0)
        self.assertAlmostEqual(calorie_score_from_median(500), 0.5)
        self.assertIsNone(calorie_score_from_median(None))

    def test_calorie_score_for_name_requires_enough_meals(self):
        _meal(menu_item_id="1", item_name="A", calories=300, protein=20)
        _meal(menu_item_id="2", item_name="B", calories=400, protein=20)
        clear_menustat_cache()
        self.assertIsNone(calorie_score_for_name("Test Chain"))
        _meal(menu_item_id="3", item_name="C", calories=500, protein=20)
        clear_menustat_cache()
        score = calorie_score_for_name("Test Chain")
        self.assertIsNotNone(score)
        self.assertAlmostEqual(score, calorie_score_from_median(400))


class RestaurantDetailMenuStatTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        clear_menustat_cache()

    def tearDown(self):
        clear_menustat_cache()

    def test_detail_shows_top5_when_linked(self):
        RestaurantInspection.objects.create(
            camis="500",
            dba="Test Chain",
            boro="Manhattan",
            street="1 Main",
            zipcode="10001",
            cuisine="American",
            inspection_date="2024-01-01",
            grade="A",
        )
        for i, cal in enumerate([250, 300, 350, 400, 450, 500], start=1):
            _meal(
                menu_item_id=f"d{i}",
                item_name=f"Dish {i}",
                calories=float(cal),
                protein=22,
            )
        clear_menustat_cache()
        response = self.client.get(reverse("search:restaurant_detail", args=["500"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["menu_picks"]), 5)
        content = response.content.decode()
        self.assertIn("Lower-calorie menu items (MenuStat)", content)
        self.assertIn("Dish 1", content)
        self.assertIn("historical", content.casefold())

    def test_detail_omits_menu_when_unmatched(self):
        RestaurantInspection.objects.create(
            camis="501",
            dba="Local Only Bistro",
            boro="Brooklyn",
            street="2 Side",
            zipcode="11201",
            cuisine="American",
            inspection_date="2024-01-01",
            grade="A",
        )
        response = self.client.get(reverse("search:restaurant_detail", args=["501"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["menu_picks"], [])
        self.assertNotIn(
            "Lower-calorie menu items (MenuStat)", response.content.decode()
        )
