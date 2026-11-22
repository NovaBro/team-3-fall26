"""Google place types map onto the cuisine labels the ranking code uses."""

from django.test import SimpleTestCase

from restaurants.boroughs import borough_for_place, borough_for_zip
from restaurants.cuisines import cuisine_for_types
from search.recommend import HEALTHY_CUISINES, NON_MEAL_CUISINES


class CuisineForTypesTests(SimpleTestCase):
    def test_primary_type_wins(self):
        self.assertEqual(
            cuisine_for_types("sushi_restaurant", ["thai_restaurant"]), "Japanese"
        )

    def test_falls_back_to_other_types(self):
        self.assertEqual(
            cuisine_for_types("restaurant", ["food", "pizza_restaurant"]), "Pizza"
        )

    def test_generic_types_give_no_cuisine(self):
        self.assertEqual(cuisine_for_types("restaurant", ["food", "bar"]), "")
        self.assertEqual(cuisine_for_types("", []), "")

    def test_unknown_restaurant_type_becomes_its_own_label(self):
        self.assertEqual(cuisine_for_types("uzbek_restaurant"), "Uzbek")
        self.assertEqual(cuisine_for_types("liquor_store"), "")

    def test_labels_feed_the_health_and_meal_rules(self):
        self.assertIn(cuisine_for_types("salad_shop"), HEALTHY_CUISINES)
        self.assertIn(cuisine_for_types("juice_shop"), HEALTHY_CUISINES)
        self.assertIn(cuisine_for_types("coffee_shop"), NON_MEAL_CUISINES)
        self.assertIn(cuisine_for_types("donut_shop"), NON_MEAL_CUISINES)


class BoroughTests(SimpleTestCase):
    def test_sublocality_names(self):
        components = [{"longText": "The Bronx", "types": ["sublocality_level_1"]}]
        self.assertEqual(borough_for_place(components), "Bronx")

    def test_zip_fallback(self):
        self.assertEqual(borough_for_place([], "11217"), "Brooklyn")
        self.assertEqual(borough_for_zip("10301"), "Staten Island")
        self.assertEqual(borough_for_zip("11375"), "Queens")
        self.assertEqual(borough_for_zip("07030"), "")
