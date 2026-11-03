from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse

from restaurants.forms import RestaurantFilterForm
from restaurants.places import PlacesError, build_request, distance_m, get_restaurants

# Washington Square Park, and places roughly 0.1 mi, 0.7 mi and 3 mi away.
WSP = (40.7308, -73.9973)
FAKE = {
    "places": [
        {
            "id": "a",
            "displayName": {"text": "Cheap Veg"},
            "formattedAddress": "1 A St",
            "priceLevel": "PRICE_LEVEL_INEXPENSIVE",
            "servesVegetarianFood": True,
            "location": {"latitude": 40.7320, "longitude": -73.9980},
        },
        {
            "id": "b",
            "displayName": {"text": "Mid Meat"},
            "formattedAddress": "2 B St",
            "priceLevel": "PRICE_LEVEL_MODERATE",
            "servesVegetarianFood": False,
            "location": {"latitude": 40.7400, "longitude": -73.9900},
        },
        {
            "id": "c",
            "displayName": {"text": "No Price"},
            "formattedAddress": "3 C St",
            "location": {"latitude": 40.7000, "longitude": -73.9500},
        },
    ]
}


def fake_response(status=200, data=FAKE):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    return r


def names(results):
    return [r["name"] for r in results]


class BuildRequestTests(SimpleTestCase):
    def test_area_search_is_restricted_to_nyc(self):
        body = build_request(area="East Village")
        self.assertEqual(body["textQuery"], "restaurants in East Village, New York, NY")
        self.assertIn("locationRestriction", body)
        self.assertNotIn("locationBias", body)

    def test_no_area_searches_all_of_nyc(self):
        self.assertEqual(build_request()["textQuery"], "restaurants in New York, NY")

    def test_price_range_sent_to_google(self):
        body = build_request(prices=["$", "$$"])
        self.assertEqual(
            body["priceLevels"], ["PRICE_LEVEL_INEXPENSIVE", "PRICE_LEVEL_MODERATE"]
        )

    def test_vegan_uses_strict_place_type(self):
        body = build_request(diet="vegan")
        self.assertEqual(body["includedType"], "vegan_restaurant")
        self.assertTrue(body["strictTypeFiltering"])

    def test_pescatarian_uses_seafood_place_type(self):
        body = build_request(diet="pescatarian")
        self.assertEqual(body["textQuery"], "seafood restaurants in New York, NY")
        self.assertEqual(body["includedType"], "seafood_restaurant")

    def test_keto_uses_text_query_only(self):
        body = build_request(diet="keto", area="Queens")
        self.assertEqual(
            body["textQuery"], "keto-friendly restaurants in Queens, New York, NY"
        )
        self.assertNotIn("includedType", body)

    def test_cuisine_is_prepended_to_query(self):
        body = build_request(cuisine="Thai", area="Manhattan")
        self.assertEqual(
            body["textQuery"], "Thai restaurants in Manhattan, New York, NY"
        )

    def test_open_now_is_only_sent_when_checked(self):
        self.assertNotIn("openNow", build_request())
        self.assertIs(build_request(open_now=True)["openNow"], True)

    def test_minimum_rating_is_sent_as_float(self):
        body = build_request(min_rating="4.5")
        self.assertEqual(body["minRating"], 4.5)
        self.assertIsInstance(body["minRating"], float)

    def test_location_biases_toward_user_with_radius(self):
        body = build_request(lat=WSP[0], lng=WSP[1], radius_m=800)
        self.assertEqual(body["textQuery"], "restaurants")
        self.assertEqual(body["locationBias"]["circle"]["radius"], 800)
        self.assertNotIn("locationRestriction", body)


@patch("restaurants.places.requests.post")
class GetRestaurantsTests(SimpleTestCase):
    def test_no_filters_returns_all(self, post):
        post.return_value = fake_response()
        self.assertEqual(len(get_restaurants(api_key="k")), 3)

    def test_price_filter_drops_other_and_unknown_prices(self, post):
        post.return_value = fake_response()
        self.assertEqual(
            names(get_restaurants(prices=["$"], api_key="k")), ["Cheap Veg"]
        )

    def test_price_range(self, post):
        post.return_value = fake_response()
        self.assertEqual(
            names(get_restaurants(prices=["$", "$$"], api_key="k")),
            ["Cheap Veg", "Mid Meat"],
        )

    def test_vegetarian_excludes_false_and_unknown(self, post):
        post.return_value = fake_response()
        self.assertEqual(
            names(get_restaurants(diet="vegetarian", api_key="k")), ["Cheap Veg"]
        )

    def test_multiple_filters_combine(self, post):
        post.return_value = fake_response()
        res = get_restaurants(prices=["$$"], diet="vegetarian", api_key="k")
        self.assertEqual(res, [])

    def test_distance_filter_and_sort(self, post):
        post.return_value = fake_response()
        res = get_restaurants(lat=WSP[0], lng=WSP[1], radius_m=1609, api_key="k")
        self.assertEqual(names(res), ["Cheap Veg", "Mid Meat"])
        self.assertLess(res[0]["distance_mi"], res[1]["distance_mi"])

    def test_location_without_radius_sorts_only(self, post):
        post.return_value = fake_response()
        res = get_restaurants(lat=WSP[0], lng=WSP[1], api_key="k")
        self.assertEqual(names(res), ["Cheap Veg", "Mid Meat", "No Price"])

    def test_avoid_nuts_drops_nut_heavy_primary_type(self, post):
        data = {
            "places": [
                {
                    "id": "t",
                    "displayName": {"text": "Thai Spot"},
                    "primaryType": "thai_restaurant",
                },
                {
                    "id": "p",
                    "displayName": {"text": "Pizza Spot"},
                    "primaryType": "pizza_restaurant",
                },
            ]
        }
        post.return_value = fake_response(data=data)
        self.assertEqual(
            names(get_restaurants(avoid=["nuts"], api_key="k")), ["Pizza Spot"]
        )

    def test_avoid_nuts_checks_secondary_types(self, post):
        data = {
            "places": [
                {
                    "id": "b",
                    "displayName": {"text": "Cafe"},
                    "primaryType": "cafe",
                    "types": ["cafe", "bakery", "food"],
                },
            ]
        }
        post.return_value = fake_response(data=data)
        self.assertEqual(get_restaurants(avoid=["nuts"], api_key="k"), [])

    def test_avoid_shellfish_and_nuts_combine(self, post):
        data = {
            "places": [
                {
                    "id": "s",
                    "displayName": {"text": "Oyster Bar"},
                    "primaryType": "seafood_restaurant",
                },
                {
                    "id": "t",
                    "displayName": {"text": "Thai Spot"},
                    "primaryType": "thai_restaurant",
                },
                {
                    "id": "i",
                    "displayName": {"text": "Curry House"},
                    "primaryType": "indian_restaurant",
                },
                {
                    "id": "p",
                    "displayName": {"text": "Pizza Spot"},
                    "primaryType": "pizza_restaurant",
                },
            ]
        }
        post.return_value = fake_response(data=data)
        self.assertEqual(
            names(get_restaurants(avoid=["shellfish"], api_key="k")),
            ["Curry House", "Pizza Spot"],
        )
        self.assertEqual(
            names(get_restaurants(avoid=["shellfish", "nuts"], api_key="k")),
            ["Pizza Spot"],
        )

    def test_no_avoid_keeps_nut_heavy_places(self, post):
        data = {
            "places": [
                {
                    "id": "t",
                    "displayName": {"text": "Thai Spot"},
                    "primaryType": "thai_restaurant",
                }
            ]
        }
        post.return_value = fake_response(data=data)
        self.assertEqual(names(get_restaurants(api_key="k")), ["Thai Spot"])

    def test_api_error_raises_friendly_message(self, post):
        post.return_value = fake_response(status=403)
        with self.assertRaises(PlacesError):
            get_restaurants(api_key="k")

    def test_missing_key_raises(self, post):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(PlacesError):
                get_restaurants()
        post.assert_not_called()


class DistanceTests(SimpleTestCase):
    def test_one_degree_latitude_is_about_111_km(self):
        self.assertAlmostEqual(distance_m(40, -74, 41, -74), 111195, delta=100)


class FilterFormTests(SimpleTestCase):
    def errors(self, data):
        form = RestaurantFilterForm(data)
        self.assertFalse(form.is_valid())
        return form.errors

    def test_valid_filters(self):
        form = RestaurantFilterForm(
            {
                "area": "Manhattan",
                "price": ["$", "$$"],
                "diet": "halal",
                "distance": "0.5",
                "lat": "40.73",
                "lng": "-73.99",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertAlmostEqual(form.radius_m, 804.672)

    def test_invalid_price(self):
        self.assertIn("price", self.errors({"price": ["$$$$$"]}))

    def test_invalid_minimum_rating(self):
        errors = self.errors({"min_rating": "6"})
        self.assertIn("Choose a minimum rating from the list.", errors["min_rating"])

    def test_invalid_cuisine(self):
        errors = self.errors({"cuisine": "Martian"})
        self.assertIn("Choose a cuisine from the list.", errors["cuisine"])

    def test_invalid_diet(self):
        self.assertIn("diet", self.errors({"diet": "paleo"}))

    def test_invalid_distance(self):
        self.assertIn(
            "distance", self.errors({"distance": "100", "lat": "40.7", "lng": "-74"})
        )

    def test_distance_needs_location(self):
        self.assertIn("distance", self.errors({"distance": "1"}))

    def test_out_of_range_latitude(self):
        self.assertIn("lat", self.errors({"lat": "999", "lng": "-73"}))

    def test_non_numeric_latitude(self):
        self.assertIn("lat", self.errors({"lat": "abc", "lng": "-73"}))

    def test_incomplete_location(self):
        self.assertIn("__all__", self.errors({"lat": "40.7"}))

    def test_invalid_allergy(self):
        self.assertIn("avoid", self.errors({"avoid": ["gluten"]}))

    def test_new_diets_are_valid(self):
        for diet in ["pescatarian", "keto"]:
            self.assertTrue(RestaurantFilterForm({"diet": diet}).is_valid())

    def test_kosher_not_offered_on_google_search(self):
        self.assertIn("diet", self.errors({"diet": "kosher"}))

    def test_area_not_in_list(self):
        self.assertIn("area", self.errors({"area": "East Village"}))

    def test_area_bad_characters(self):
        self.assertIn("area", self.errors({"area": "<script>"}))


@patch("restaurants.views.get_restaurants")
class SearchViewTests(SimpleTestCase):
    url = reverse("restaurants:search")

    def test_page_loads_without_search(self, gr):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Choose filters and press Search.")
        gr.assert_not_called()

    def test_filters_are_passed_together(self, gr):
        gr.return_value = []
        self.client.get(
            self.url,
            {
                "area": "Manhattan",
                "price": ["$", "$$"],
                "diet": "vegan",
                "distance": "1",
                "lat": "40.73",
                "lng": "-73.99",
                "cuisine": "",
                "open_now": "",
                "min_rating": "",
            },
        )
        gr.assert_called_once_with(
            area="Manhattan",
            prices=["$", "$$"],
            diet="vegan",
            lat=40.73,
            lng=-73.99,
            radius_m=1609.344,
            avoid=[],
            cuisine="",
            open_now=False,
            min_rating=None,
        )

    def test_results_are_shown(self, gr):
        gr.return_value = [
            {
                "name": "Test Place",
                "address": "x",
                "price": "$$",
                "vegetarian": True,
                "lat": 40.7,
                "lng": -74.0,
                "maps_url": "",
                "distance_mi": 0.3,
            }
        ]
        resp = self.client.get(self.url, {"area": "Brooklyn", "price": "$$"})
        self.assertContains(resp, "Test Place")
        self.assertContains(resp, "1 restaurant found.")
        self.assertContains(resp, "0.30 mi away")

    def test_allergy_filter_shows_disclaimer(self, gr):
        gr.return_value = []
        resp = self.client.get(self.url, {"area": "Queens", "avoid": "nuts"})
        self.assertEqual(gr.call_args.kwargs["avoid"], ["nuts"])
        self.assertContains(resp, "Always confirm allergies with the restaurant.")

    def test_no_disclaimer_without_allergy_filter(self, gr):
        gr.return_value = []
        resp = self.client.get(self.url, {"area": "Queens"})
        self.assertNotContains(resp, "Always confirm allergies")

    def test_no_results_message(self, gr):
        gr.return_value = []
        resp = self.client.get(self.url, {"area": "Brooklyn", "price": "$$$$"})
        self.assertContains(resp, "No results")

    def test_invalid_filter_shows_error_and_skips_search(self, gr):
        resp = self.client.get(self.url, {"area": "Brooklyn", "price": "cheap"})
        self.assertContains(resp, "Please fix these filters")
        self.assertContains(resp, "cheap is not a valid price")
        self.assertNotContains(resp, "No results")
        gr.assert_not_called()

    def test_data_source_error_is_shown(self, gr):
        gr.side_effect = PlacesError("boom")
        resp = self.client.get(self.url, {"area": "Queens"})
        self.assertContains(resp, "boom")
        self.assertNotContains(resp, "No results")

    def test_location_can_be_cleared(self, gr):
        gr.return_value = []
        resp = self.client.get(self.url, {"area": "", "lat": "40.73", "lng": "-73.99"})
        self.assertContains(resp, "Using your location")
        self.assertContains(resp, 'id="clear-location"')
        resp = self.client.get(self.url, {"area": ""})
        self.assertNotContains(resp, 'id="clear-location"')

    def test_missing_map_key_is_not_an_error(self, gr):
        gr.return_value = [
            {
                "name": "P",
                "address": "",
                "price": "",
                "vegetarian": None,
                "lat": 40.7,
                "lng": -74.0,
                "maps_url": "",
                "distance_mi": None,
            }
        ]
        with patch.dict("os.environ", {"GOOGLE_MAPS_JS_KEY": ""}):
            resp = self.client.get(self.url, {"area": "Queens"})
        self.assertContains(resp, "Map not shown")
        self.assertNotContains(resp, 'class="error"')

    def test_nav_link_on_existing_pages(self, gr):
        self.assertContains(self.client.get(reverse("search:index")), self.url)
