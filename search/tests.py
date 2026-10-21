from django.test import TestCase
from django.urls import reverse

from search.models import FarmersMarket, RestaurantInspection


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
