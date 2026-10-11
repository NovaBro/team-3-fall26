from django.test import TestCase
from django.urls import reverse

from search.models import FarmersMarket, RestaurantInspection


class RestaurantSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        RestaurantInspection.objects.create(
            camis="1", dba="Joe's Pizza", boro="Brooklyn",
            street="1 Main St", zipcode="11201",
            inspection_date="2024-01-01", grade="A",
        )
        RestaurantInspection.objects.create(
            camis="1", dba="Joe's Pizza", boro="Brooklyn",
            street="1 Main St", zipcode="11201",
            inspection_date="2025-01-01", grade="B",
        )
        RestaurantInspection.objects.create(
            camis="2", dba="Taco Town", boro="Queens",
            street="2 Main St", zipcode="11101",
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
        response = self.client.get(reverse("search:index"), {"boro": "Queens"})
        self.assertEqual(len(response.context["page_obj"]), 1)

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
