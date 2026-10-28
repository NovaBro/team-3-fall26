from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from restaurants.places import PlacesError
from search.models import (
    FarmersMarket,
    HealthyStore,
    PlaceEnrichment,
    PlaceReview,
    RestaurantInspection,
)
from search.services.places import PlacesAPIError, enrich_camis


class RestaurantSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        RestaurantInspection.objects.create(
            camis="1", dba="Joe's Pizza", boro="Brooklyn",
            street="1 Main St", zipcode="11201", cuisine="Pizza",
            inspection_date="2024-01-01", grade="A",
        )
        RestaurantInspection.objects.create(
            camis="1", dba="Joe's Pizza", boro="Brooklyn",
            street="1 Main St", zipcode="11201", cuisine="Pizza",
            inspection_date="2025-01-01", grade="B",
        )
        RestaurantInspection.objects.create(
            camis="3", dba="Green Leaf", boro="Manhattan",
            street="3 Main St", zipcode="10003", cuisine="Vegan",
            inspection_date="2024-06-01", grade="A",
        )
        RestaurantInspection.objects.create(
            camis="4", dba="Thai Garden", boro="Queens",
            street="4 Main St", zipcode="11101", cuisine="Thai",
            inspection_date="2024-07-01", grade="A",
        )
        RestaurantInspection.objects.create(
            camis="2", dba="Taco Town", boro="Queens",
            street="2 Main St", zipcode="11101", cuisine="Mexican",
            inspection_date="2024-05-01", grade="A",
        )

    def test_home_without_filters_has_no_results(self):
        response = self.client.get(reverse("search:index"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["searched"])

    def test_search_by_name(self):
        response = self.client.get(reverse("search:index"), {"q": "pizza"})
        self.assertEqual(len(response.context["page_obj"]), 1)

    def test_search_returns_latest_grade(self):
        response = self.client.get(reverse("search:index"), {"q": "pizza"})
        row = response.context["page_obj"][0]
        self.assertEqual(row["grade"], "B")

    def test_search_filter_by_borough(self):
        response = self.client.get(reverse("search:index"), {"boro": "Queens", "q": "taco"})
        self.assertEqual(len(response.context["page_obj"]), 1)

    def names(self, params):
        response = self.client.get(reverse("search:index"), params)
        return sorted(row["name"] for row in response.context["page_obj"])

    def test_diet_filter_matches_specialized_cuisine(self):
        self.assertEqual(self.names({"diet": "vegan"}), ["Green Leaf"])
        self.assertEqual(self.names({"diet": "vegetarian"}), ["Green Leaf"])

    def test_unknown_diet_is_ignored(self):
        response = self.client.get(reverse("search:index"), {"diet": "paleo"})
        self.assertFalse(response.context["searched"])

    def test_avoid_nuts_excludes_nut_heavy_cuisines(self):
        self.assertEqual(
            self.names({"avoid": "nuts"}), ["Green Leaf", "Joe's Pizza", "Taco Town"]
        )

    def test_pescatarian_includes_seafood_and_vegetarian(self):
        RestaurantInspection.objects.create(camis="5", dba="Fish Shack", cuisine="Seafood")
        self.assertEqual(self.names({"diet": "pescatarian"}), ["Fish Shack", "Green Leaf"])

    def test_keto_matches_low_carb_cuisines(self):
        RestaurantInspection.objects.create(camis="6", dba="Prime Cuts", cuisine="Steakhouse")
        self.assertEqual(self.names({"diet": "keto"}), ["Prime Cuts"])

    def test_halal_not_offered_on_homepage(self):
        response = self.client.get(reverse("search:index"), {"diet": "halal"})
        self.assertFalse(response.context["searched"])

    def test_avoid_shellfish_excludes_shellfish_heavy_cuisines(self):
        RestaurantInspection.objects.create(camis="7", dba="Oyster Bar", cuisine="Seafood")
        self.assertEqual(
            self.names({"avoid": "shellfish"}), ["Green Leaf", "Joe's Pizza", "Taco Town"]
        )

    def test_avoid_nuts_shows_disclaimer(self):
        response = self.client.get(reverse("search:index"), {"avoid": "nuts"})
        self.assertContains(response, "Always confirm allergies with the restaurant.")

    def test_results_show_cuisine(self):
        response = self.client.get(reverse("search:index"), {"q": "thai"})
        self.assertContains(response, "<td>Thai</td>", html=True)

    def test_detail_renders_history(self):
        response = self.client.get(
            reverse("search:restaurant_detail", args=["1"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dba"], "Joe's Pizza")
        self.assertEqual(len(response.context["inspections"]), 2)

    def test_detail_missing_returns_404(self):
        response = self.client.get(
            reverse("search:restaurant_detail", args=["999"])
        )
        self.assertEqual(response.status_code, 404)


class ExploreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        FarmersMarket.objects.create(
            year=2024, market_name="Union Square Greenmarket",
            borough="Manhattan", street_address="E 17th St",
        )

    def test_explore_index_lists_datasets(self):
        response = self.client.get(reverse("search:explore_index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Farmers Markets")

    def test_explore_dataset_search(self):
        response = self.client.get(
            reverse("search:explore", args=["farmers-markets"]),
            {"q": "union"},
        )
        self.assertEqual(len(response.context["page_obj"]), 1)

    def test_explore_unknown_dataset_404(self):
        response = self.client.get(reverse("search:explore", args=["nope"]))
        self.assertEqual(response.status_code, 404)


class FarmersMarketMapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        FarmersMarket.objects.create(
            year=2025,
            market_name="Older Market Listing",
            borough="Manhattan",
            latitude=40.7,
            longitude=-74.0,
        )
        FarmersMarket.objects.create(
            year=2026,
            market_name="Union Square Greenmarket",
            borough="Manhattan",
            street_address="E 17th St",
            latitude=40.737,
            longitude=-73.99,
            days_of_operation="Monday",
            hours_of_operations="8 a.m. - 6 p.m.",
        )
        FarmersMarket.objects.create(
            year=2026,
            market_name="Market Without Coordinates",
            borough="Queens",
        )
        FarmersMarket.objects.create(
            year=2026,
            market_name="Saratoga Farm Stand",
            borough="Brooklyn",
            street_address="1965-1971 Fulton St.",
            latitude=40.68,
            longitude=-0.00008,
            days_of_operation="Tuesday-Saturday",
            hours_of_operations="10 a.m. - 2 p.m.",
        )

    def test_map_shows_latest_year_markets_and_corrects_saratoga_location(self):
        response = self.client.get(reverse("search:farmers_markets_map"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["market_year"], 2026)
        self.assertEqual(len(response.context["markets"]), 2)
        markets_by_name = {
            market["market_name"]: market for market in response.context["markets"]
        }
        self.assertIn("Union Square Greenmarket", markets_by_name)
        saratoga = markets_by_name["Saratoga Farm Stand"]
        self.assertEqual(saratoga["street_address"], "1965 Fulton St, Brooklyn, NY 11233")
        self.assertEqual(saratoga["zip_code"], "11233")
        self.assertEqual(saratoga["latitude"], 40.6785)
        self.assertEqual(saratoga["longitude"], -73.916194)

    def test_map_can_filter_by_market_name(self):
        response = self.client.get(
            reverse("search:farmers_markets_map"), {"q": "union"}
        )
        self.assertEqual(len(response.context["markets"]), 1)
        self.assertEqual(response.context["name"], "union")
        self.assertContains(response, 'value="union"')

    def test_map_can_filter_by_zip_code(self):
        response = self.client.get(
            reverse("search:farmers_markets_map"), {"zip": "11233"}
        )
        self.assertEqual(len(response.context["markets"]), 1)
        self.assertEqual(
            response.context["markets"][0]["market_name"], "Saratoga Farm Stand"
        )
        self.assertEqual(response.context["zip"], "11233")

    def test_map_can_filter_by_day_of_week(self):
        response = self.client.get(
            reverse("search:farmers_markets_map"), {"day": "Wednesday"}
        )
        self.assertEqual(len(response.context["markets"]), 1)
        self.assertEqual(
            response.context["markets"][0]["market_name"], "Saratoga Farm Stand"
        )
        self.assertEqual(response.context["day"], "Wednesday")
        self.assertContains(response, '<option value="Wednesday" selected>')

    def test_map_renders_popup_data_script(self):
        response = self.client.get(reverse("search:farmers_markets_map"))
        self.assertContains(response, 'id="farmers-market-data"')
        self.assertContains(response, "farmers_markets_map.js")
        self.assertNotContains(response, "Listings not shown on the map")
        self.assertNotContains(response, "Market Without Coordinates")


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


SEARCH_RESULT = {
    "places": [
        {
            "id": "ChIJtest",
            "displayName": {"text": "Joe's Pizza"},
            "formattedAddress": "1 Main St, Brooklyn, NY 11201",
            "location": {"latitude": 40.7, "longitude": -73.9},
        }
    ]
}

DETAILS_RESULT = {
    "id": "ChIJtest",
    "displayName": {"text": "Joe's Pizza"},
    "formattedAddress": "1 Main St, Brooklyn, NY 11201",
    "location": {"latitude": 40.7, "longitude": -73.99},
    "rating": 4.5,
    "userRatingCount": 3210,
    "priceLevel": "PRICE_LEVEL_INEXPENSIVE",
    "websiteUri": "https://joes.example",
    "googleMapsUri": "https://maps.google.com/?cid=1",
    "businessStatus": "OPERATIONAL",
    "reviews": [
        {
            "rating": 5,
            "relativePublishTimeDescription": "a month ago",
            "text": {"text": "Best slice in Brooklyn."},
            "authorAttribution": {
                "displayName": "Sam",
                "uri": "https://maps.google.com/contrib/1",
            },
            "publishTime": "2025-09-01T12:00:00Z",
        }
    ],
}


@override_settings(GOOGLE_PLACES_API_KEY="test-key")
class EnrichRestaurantTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        RestaurantInspection.objects.create(
            camis="1", dba="Joe's Pizza", boro="Brooklyn",
            street="1 Main St", zipcode="11201",
            inspection_date="2025-01-01", grade="A",
        )

    @patch("search.services.places.requests.request")
    def test_enrich_saves_place_and_reviews(self, request):
        request.side_effect = [
            _FakeResponse(SEARCH_RESULT),
            _FakeResponse(DETAILS_RESULT),
        ]
        enrichment = enrich_camis("1")
        self.assertEqual(enrichment.place_id, "ChIJtest")
        self.assertEqual(enrichment.rating, 4.5)
        self.assertEqual(enrichment.user_rating_count, 3210)
        self.assertEqual(enrichment.price_level_display, "$")
        self.assertEqual(enrichment.reviews.count(), 1)
        self.assertEqual(enrichment.reviews.first().author_name, "Sam")

    @patch("search.services.places.requests.request")
    def test_refetch_replaces_reviews(self, request):
        request.side_effect = [
            _FakeResponse(SEARCH_RESULT),
            _FakeResponse(DETAILS_RESULT),
        ]
        enrich_camis("1")
        request.side_effect = [
            _FakeResponse(SEARCH_RESULT),
            _FakeResponse(DETAILS_RESULT),
        ]
        enrich_camis("1")
        self.assertEqual(PlaceEnrichment.objects.count(), 1)
        self.assertEqual(PlaceReview.objects.count(), 1)

    @patch("search.services.places.requests.request")
    def test_no_match_raises(self, request):
        request.return_value = _FakeResponse({"places": []})
        with self.assertRaises(PlacesAPIError):
            enrich_camis("1")

    @patch("search.services.places.requests.request")
    def test_api_error_raises(self, request):
        request.return_value = _FakeResponse(
            {"error": {"message": "denied"}}, status_code=403
        )
        with self.assertRaises(PlacesAPIError):
            enrich_camis("1")

    @override_settings(GOOGLE_PLACES_API_KEY="")
    def test_missing_key_raises(self):
        with self.assertRaises(PlacesAPIError):
            enrich_camis("1")


class RestaurantDetailGoogleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        RestaurantInspection.objects.create(
            camis="1", dba="Joe's Pizza", boro="Brooklyn",
            street="1 Main St", zipcode="11201",
            inspection_date="2025-01-01", grade="A",
        )

    def test_detail_shows_stored_google_data(self):
        place = PlaceEnrichment.objects.create(
            camis="1", place_id="ChIJtest", display_name="Joe's Pizza",
            rating=4.5, user_rating_count=3210,
            price_level="PRICE_LEVEL_INEXPENSIVE",
        )
        PlaceReview.objects.create(
            place=place, author_name="Sam", rating=5, text="Great slice.",
        )
        response = self.client.get(
            reverse("search:restaurant_detail", args=["1"])
        )
        self.assertContains(response, "4.5")
        self.assertContains(response, "Great slice.")

    def test_detail_without_google_data_prompts(self):
        response = self.client.get(
            reverse("search:restaurant_detail", args=["1"])
        )
        self.assertContains(response, "No Google data stored yet")

    @patch("search.views.enrich_camis")
    def test_refresh_post_enriches_and_redirects(self, enrich):
        response = self.client.post(
            reverse("search:refresh_place", args=["1"])
        )
        self.assertRedirects(
            response, reverse("search:restaurant_detail", args=["1"])
        )
        enrich.assert_called_once_with("1")

    @patch("search.views.enrich_camis", side_effect=PlacesAPIError("boom"))
    def test_refresh_post_reports_error(self, enrich):
        response = self.client.post(
            reverse("search:refresh_place", args=["1"]), follow=True
        )
        self.assertContains(response, "Could not fetch Google data")

    def test_refresh_get_not_allowed(self):
        response = self.client.get(
            reverse("search:refresh_place", args=["1"])
        )
        self.assertEqual(response.status_code, 405)


class CombinedMapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        FarmersMarket.objects.create(
            year=2026,
            market_name="Union Square Greenmarket",
            borough="Manhattan",
            street_address="E 17th St",
            latitude=40.737,
            longitude=-73.99,
        )
        FarmersMarket.objects.create(
            year=2026,
            market_name="Market Without Coordinates",
            borough="Queens",
        )
        HealthyStore.objects.create(
            store_name="Healthy Corner",
            street_address="100 Main St",
            borough="Brooklyn",
            zip_code="11201",
            latitude=40.69,
            longitude=-73.98,
        )
        HealthyStore.objects.create(
            store_name="Queens Pantry",
            street_address="200 Queens Blvd",
            borough="Queens",
            zip_code="11375",
            latitude=40.72,
            longitude=-73.84,
        )
        RestaurantInspection.objects.create(
            camis="1",
            dba="Joe's Pizza",
            boro="Brooklyn",
            street="1 Main St",
            zipcode="11201",
        )
        PlaceEnrichment.objects.create(
            camis="1",
            place_id="ChIJtest",
            display_name="Joe's Pizza",
            formatted_address="1 Main St, Brooklyn, NY 11201",
            latitude=40.695,
            longitude=-73.985,
            rating=4.5,
        )

    def test_nav_link_and_page_load(self):
        response = self.client.get(reverse("search:combined_map"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Combined map")
        self.assertContains(response, reverse("search:combined_map"))
        self.assertContains(response, "combined_map.js")

    def test_static_points_include_expected_categories(self):
        response = self.client.get(reverse("search:combined_map"))
        points = response.context["static_points"]
        by_category = {}
        for point in points:
            by_category.setdefault(point["category"], []).append(point)

        self.assertEqual(len(by_category["farmers_market"]), 1)
        self.assertEqual(
            by_category["farmers_market"][0]["name"], "Union Square Greenmarket"
        )
        self.assertEqual(len(by_category["grocery"]), 2)
        self.assertEqual(len(by_category["restaurant_dohmh"]), 1)
        self.assertEqual(by_category["restaurant_dohmh"][0]["name"], "Joe's Pizza")
        self.assertEqual(
            by_category["restaurant_dohmh"][0]["url"],
            reverse("search:restaurant_detail", args=["1"]),
        )
        self.assertNotIn("restaurant_google", by_category)

    def test_filters_narrow_results(self):
        response = self.client.get(
            reverse("search:combined_map"), {"boro": "Brooklyn", "q": "Healthy"}
        )
        points = response.context["static_points"]
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["category"], "grocery")
        self.assertEqual(points[0]["name"], "Healthy Corner")

        zip_response = self.client.get(
            reverse("search:combined_map"), {"zip": "11201"}
        )
        zip_points = zip_response.context["static_points"]
        categories = {point["category"] for point in zip_points}
        self.assertIn("grocery", categories)
        self.assertIn("restaurant_dohmh", categories)
        self.assertNotIn("farmers_market", categories)

    @patch("search.views.get_restaurants")
    def test_google_endpoint_returns_google_category(self, get_restaurants):
        get_restaurants.return_value = [
            {
                "name": "Live Spot",
                "lat": 40.73,
                "lng": -73.99,
                "address": "123 Ave A",
                "maps_url": "https://maps.google.com/?cid=9",
            }
        ]
        response = self.client.get(
            reverse("search:combined_map_google"), {"area": "Manhattan"}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["error"], "")
        self.assertEqual(len(payload["points"]), 1)
        self.assertEqual(payload["points"][0]["category"], "restaurant_google")
        self.assertEqual(payload["points"][0]["name"], "Live Spot")
        get_restaurants.assert_called_once()

        static = self.client.get(reverse("search:combined_map")).context[
            "static_points"
        ]
        self.assertTrue(
            all(point["category"] != "restaurant_google" for point in static)
        )

    @patch("search.views.get_restaurants", side_effect=PlacesError("missing key"))
    def test_google_endpoint_reports_places_error_as_502(self, _get_restaurants):
        response = self.client.get(reverse("search:combined_map_google"))
        self.assertEqual(response.status_code, 502)
        self.assertIn("missing key", response.json()["error"])
