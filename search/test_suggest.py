from django.test import TestCase

from community.models import Restaurant
from nycfood.test_utils import ALL_DATABASES
from search.models import FarmersMarket, HealthyStore


class SearchSuggestTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        for i, name in enumerate(["Apple Bistro", "Avocado Bar", "Banana Cafe"]):
            Restaurant.objects.create(name=name, place_id=f"p{i}", rating_count=10 - i)
        FarmersMarket.objects.create(year=2026, market_name="Astoria Greenmarket")
        HealthyStore.objects.create(store_name="Aunt Grocery")

    def get(self, q):
        return self.client.get("/search/suggest/", {"q": q}).json()["items"]

    def test_empty_query(self):
        self.assertEqual(self.get(""), [])

    def test_one_letter_matches_start_of_name(self):
        names = [i["name"] for i in self.get("a")]
        self.assertEqual(names[:2], ["Apple Bistro", "Avocado Bar"])
        self.assertIn("Astoria Greenmarket", names)
        self.assertIn("Aunt Grocery", names)
        self.assertNotIn("Banana Cafe", names)

    def test_two_letters_match_anywhere_and_keys(self):
        items = self.get("caf")
        self.assertEqual(items[0]["name"], "Banana Cafe")
        self.assertEqual(items[0]["key"], "google:p2")
        self.assertEqual(items[0]["kind"], "Restaurant")

    def test_at_most_five(self):
        for i in range(8):
            Restaurant.objects.create(name=f"Zed {i}", place_id=f"z{i}")
        self.assertEqual(len(self.get("z")), 5)
