from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from community.keys import DOHMH, FARMERS_MARKET, GROCERY, dohmh_key
from community.models import PlaceEnrichment, PlaceReview
from search.models import RestaurantInspection
from search.services.places import PlacesAPIError, enrich_camis, enrich_subject


@patch.dict("os.environ", {"GOOGLE_API_KEY": ""})
class RestaurantSearchTests(TestCase):
    databases = {"default", "community"}

    @classmethod
    def setUpTestData(cls):
        RestaurantInspection.objects.create(
            camis="1",
            dba="Joe's Pizza",
            boro="Brooklyn",
            street="1 Main St",
            zipcode="11201",
            cuisine="Pizza",
            inspection_date="2024-01-01",
            grade="A",
        )
        RestaurantInspection.objects.create(
            camis="1",
            dba="Joe's Pizza",
            boro="Brooklyn",
            street="1 Main St",
            zipcode="11201",
            cuisine="Pizza",
            inspection_date="2025-01-01",
            grade="B",
        )
        RestaurantInspection.objects.create(
            camis="3",
            dba="Green Leaf",
            boro="Manhattan",
            street="3 Main St",
            zipcode="10003",
            cuisine="Vegan",
            inspection_date="2024-06-01",
            grade="A",
        )
        RestaurantInspection.objects.create(
            camis="4",
            dba="Thai Garden",
            boro="Queens",
            street="4 Main St",
            zipcode="11101",
            cuisine="Thai",
            inspection_date="2024-07-01",
            grade="A",
        )
        RestaurantInspection.objects.create(
            camis="2",
            dba="Taco Town",
            boro="Queens",
            street="2 Main St",
            zipcode="11101",
            cuisine="Mexican",
            inspection_date="2024-05-01",
            grade="A",
        )

    def get(self, params=None):
        return self.client.get(
            reverse("search:index"), {"types": "restaurant", **(params or {})}
        )

    def names(self, params):
        return sorted(item["name"] for item in self.get(params).context["items"])

    def test_landing_lists_every_restaurant_once(self):
        response = self.client.get(reverse("search:index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(item["name"] for item in response.context["items"]),
            ["Green Leaf", "Joe's Pizza", "Taco Town", "Thai Garden"],
        )

    def test_search_by_name(self):
        self.assertEqual(self.names({"q": "pizza"}), ["Joe's Pizza"])

    def test_search_returns_latest_grade(self):
        item = self.get({"q": "pizza"}).context["items"][0]
        self.assertEqual(item["grade"], "B")
        self.assertEqual(item["key"], "camis:1")
        self.assertEqual(item["url"], reverse("search:restaurant_detail", args=["1"]))

    def test_grade_filter_uses_latest_grade(self):
        self.assertEqual(self.names({"grade": "B"}), ["Joe's Pizza"])
        self.assertNotIn("Joe's Pizza", self.names({"grade": "A"}))

    def test_search_filter_by_borough(self):
        self.assertEqual(self.names({"area": "Queens", "q": "taco"}), ["Taco Town"])

    def test_search_filter_by_zip_prefix(self):
        self.assertEqual(self.names({"zip": "111"}), ["Taco Town", "Thai Garden"])

    def test_cuisine_filter(self):
        self.assertEqual(self.names({"cuisine": "Thai"}), ["Thai Garden"])

    def test_diet_filter_matches_specialized_cuisine(self):
        self.assertEqual(self.names({"diet": "vegan"}), ["Green Leaf"])
        self.assertEqual(self.names({"diet": "vegetarian"}), ["Green Leaf"])

    def test_unknown_diet_is_rejected(self):
        response = self.get({"diet": "paleo"})
        self.assertIn("diet", response.context["form"].errors)
        self.assertEqual(response.context["items"], [])

    def test_avoid_nuts_excludes_nut_heavy_cuisines(self):
        self.assertEqual(
            self.names({"avoid": "nuts"}), ["Green Leaf", "Joe's Pizza", "Taco Town"]
        )

    def test_pescatarian_includes_seafood_and_vegetarian(self):
        RestaurantInspection.objects.create(
            camis="5", dba="Fish Shack", cuisine="Seafood"
        )
        self.assertEqual(
            self.names({"diet": "pescatarian"}), ["Fish Shack", "Green Leaf"]
        )

    def test_keto_matches_low_carb_cuisines(self):
        RestaurantInspection.objects.create(
            camis="6", dba="Prime Cuts", cuisine="Steakhouse"
        )
        self.assertEqual(self.names({"diet": "keto"}), ["Prime Cuts"])

    def test_halal_needs_google_places(self):
        response = self.get({"diet": "halal"})
        self.assertContains(response, "Halal is only available with Google Places")
        self.assertEqual(response.context["items"], [])

    def test_avoid_shellfish_excludes_shellfish_heavy_cuisines(self):
        RestaurantInspection.objects.create(
            camis="7", dba="Oyster Bar", cuisine="Seafood"
        )
        self.assertEqual(
            self.names({"avoid": "shellfish"}),
            ["Green Leaf", "Joe's Pizza", "Taco Town"],
        )

    def test_avoid_nuts_shows_disclaimer(self):
        response = self.get({"avoid": "nuts"})
        self.assertContains(response, "Always confirm allergies with the restaurant.")

    def test_results_show_cuisine(self):
        self.assertContains(self.get({"q": "thai"}), "Thai · Inspected Jul 2024")

    def test_detail_renders_history(self):
        response = self.client.get(reverse("search:restaurant_detail", args=["1"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dba"], "Joe's Pizza")
        self.assertEqual(len(response.context["inspections"]), 2)

    def test_detail_shows_healthiness_score_breakdown(self):
        response = self.client.get(reverse("search:restaurant_detail", args=["1"]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("healthiness_score", response.context)
        breakdown = response.context["score_breakdown"]
        self.assertIsNotNone(breakdown)
        self.assertTrue(breakdown["parts"])
        content = response.content.decode()
        self.assertIn("Healthiness score", content)
        self.assertIn("How this score is calculated", content)
        self.assertIn("Health", content)
        self.assertIn("pts", content)

    def test_detail_missing_returns_404(self):
        response = self.client.get(reverse("search:restaurant_detail", args=["999"]))
        self.assertEqual(response.status_code, 404)


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
    databases = {"default", "community"}

    @classmethod
    def setUpTestData(cls):
        RestaurantInspection.objects.create(
            camis="1",
            dba="Joe's Pizza",
            boro="Brooklyn",
            street="1 Main St",
            zipcode="11201",
            inspection_date="2025-01-01",
            grade="A",
        )

    @patch("search.services.places.requests.request")
    def test_enrich_saves_place_and_reviews(self, request):
        request.side_effect = [
            _FakeResponse(SEARCH_RESULT),
            _FakeResponse(DETAILS_RESULT),
        ]
        enrichment = enrich_camis("1")
        self.assertEqual(enrichment.kind, DOHMH)
        self.assertEqual(enrichment.key, dohmh_key("1"))
        self.assertEqual(enrichment.camis, "1")
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
    databases = {"default", "community"}

    @classmethod
    def setUpTestData(cls):
        RestaurantInspection.objects.create(
            camis="1",
            dba="Joe's Pizza",
            boro="Brooklyn",
            street="1 Main St",
            zipcode="11201",
            inspection_date="2025-01-01",
            grade="A",
        )

    def test_detail_shows_stored_google_data(self):
        place = PlaceEnrichment.objects.create(
            kind=DOHMH,
            key=dohmh_key("1"),
            camis="1",
            place_id="ChIJtest",
            display_name="Joe's Pizza",
            rating=4.5,
            user_rating_count=3210,
            price_level="PRICE_LEVEL_INEXPENSIVE",
        )
        PlaceReview.objects.create(
            place=place,
            author_name="Sam",
            rating=5,
            text="Great slice.",
        )
        response = self.client.get(reverse("search:restaurant_detail", args=["1"]))
        self.assertContains(response, "4.5")
        self.assertContains(response, "Great slice.")

    def test_detail_without_google_data_prompts(self):
        response = self.client.get(reverse("search:restaurant_detail", args=["1"]))
        self.assertContains(response, "No Google data stored yet")

    @patch("search.views.enrich_camis")
    def test_refresh_post_enriches_and_redirects(self, enrich):
        response = self.client.post(reverse("search:refresh_place", args=["1"]))
        self.assertRedirects(response, reverse("search:restaurant_detail", args=["1"]))
        enrich.assert_called_once_with("1")

    @patch("search.views.enrich_camis", side_effect=PlacesAPIError("boom"))
    def test_refresh_post_reports_error(self, enrich):
        response = self.client.post(
            reverse("search:refresh_place", args=["1"]), follow=True
        )
        self.assertContains(response, "Could not fetch Google data")

    def test_refresh_get_not_allowed(self):
        response = self.client.get(reverse("search:refresh_place", args=["1"]))
        self.assertEqual(response.status_code, 405)


class HomeTopPicksTests(TestCase):
    databases = {"default", "community"}

    @patch("search.views.find_restaurant_place")
    def test_home_page_shows_top_picks_with_google_review(self, mock_find_place):
        RestaurantInspection.objects.create(
            camis="999",
            dba="Thai Garden",
            boro="Queens",
            street="4 Main St",
            zipcode="11101",
            cuisine="Thai",
            inspection_date="2024-07-01",
            grade="A",
        )
        mock_find_place.return_value = {
            "name": "Thai Garden",
            "address": "4 Main St, Queens, NY 11101",
            "street": "4 Main St",
            "zipcode": "11101",
            "price": "$$",
            "rating": 4.8,
            "rating_count": 150,
            "photo": "places/ChIJ123/photos/abc",
            "reviews": [
                {
                    "text": "Best pad thai in Queens! Must try.",
                    "author_name": "Alice M.",
                    "rating": 5,
                    "relative_time": "2 weeks ago",
                }
            ],
            "review": {
                "text": "Best pad thai in Queens! Must try.",
                "author_name": "Alice M.",
                "rating": 5,
                "relative_time": "2 weeks ago",
            },
        }
        response = self.client.get(reverse("search:home"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("top_picks", response.context)
        top_picks = response.context["top_picks"]
        self.assertTrue(len(top_picks) > 0)
        first_pick = top_picks[0]
        expected_comment = "Best pad thai in Queens! Must try."
        self.assertEqual(first_pick["review"]["text"], expected_comment)
        self.assertEqual(first_pick["review"]["author_name"], "Alice M.")
        self.assertIn("reason_tags", first_pick)
        self.assertIn("Grade A", first_pick["reason_tags"])
        self.assertIn(
            "restaurants/photo/?name=places%2FChIJ123%2Fphotos%2Fabc",
            first_pick["photo_url"],
        )
        content = response.content.decode("utf-8")
        self.assertIn("Best pad thai in Queens! Must try.", content)
        self.assertIn("Alice M.", content)
        self.assertIn("Grade A", content)
        expected_photo = "restaurants/photo/?name=places%2FChIJ123%2Fphotos%2Fabc"
        self.assertIn(expected_photo, content)

    @patch("search.views.find_restaurant_place")
    def test_top_picks_are_score_ordered_not_date_ordered(self, mock_find_place):
        # Newest inspection is pizza (unhealthy); older salad place should win.
        RestaurantInspection.objects.create(
            camis="901",
            dba="Slice House",
            boro="Brooklyn",
            street="1 Pizza Ave",
            zipcode="11201",
            cuisine="Pizza",
            inspection_date="2025-06-01",
            grade="A",
        )
        RestaurantInspection.objects.create(
            camis="902",
            dba="Green Bowl",
            boro="Manhattan",
            street="2 Salad St",
            zipcode="10003",
            cuisine="Salads",
            inspection_date="2024-01-01",
            grade="A",
        )
        RestaurantInspection.objects.create(
            camis="903",
            dba="McDonald's Midtown",
            boro="Manhattan",
            street="3 Fast Ln",
            zipcode="10001",
            cuisine="Hamburgers",
            inspection_date="2025-05-01",
            grade="A",
        )

        def fake_place(name, zipcode, street):
            healthy = (
                "fresh healthy salad grilled organic" in name or name == "Green Bowl"
            )
            return {
                "name": name,
                "address": f"{street}, NY {zipcode}",
                "street": street,
                "zipcode": zipcode,
                "price": "$" if "McDonald" in name else "$$",
                "rating": 4.0,
                "rating_count": 200,
                "photo": "",
                "reviews": (
                    [{"text": "fresh healthy salad grilled organic"}]
                    if healthy
                    else [{"text": "greasy fried salty"}]
                ),
                "review": {
                    "text": (
                        "fresh healthy salad grilled organic"
                        if healthy
                        else "greasy fried salty"
                    ),
                    "author_name": "Tester",
                    "rating": 4,
                    "relative_time": "1 week ago",
                },
            }

        mock_find_place.side_effect = fake_place
        response = self.client.get(reverse("search:home"))
        self.assertEqual(response.status_code, 200)
        names = [pick["name"] for pick in response.context["top_picks"]]
        self.assertEqual(names[0], "Green Bowl")
        self.assertNotEqual(names[0], "Slice House")
        scores = [pick["score"] for pick in response.context["top_picks"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(
            all("reason_tags" in pick for pick in response.context["top_picks"])
        )


@override_settings(GOOGLE_PLACES_API_KEY="test-key")
class EnrichSubjectTests(TestCase):
    databases = {"default", "community"}

    @patch("search.services.places.requests.request")
    def test_enrich_grocery_saves_kind_key_and_reviews(self, request):
        request.side_effect = [
            _FakeResponse(SEARCH_RESULT),
            _FakeResponse(DETAILS_RESULT),
        ]
        key = "Healthy Corner|100 Main St|11201"
        enrichment = enrich_subject(
            GROCERY, key, "Healthy Corner 100 Main St Brooklyn NY 11201"
        )
        self.assertEqual(enrichment.kind, GROCERY)
        self.assertEqual(enrichment.key, key)
        self.assertEqual(enrichment.camis, "")
        self.assertEqual(enrichment.reviews.count(), 1)

    @patch("search.services.places.requests.request")
    def test_enrich_market_refresh_replaces_reviews(self, request):
        request.side_effect = [
            _FakeResponse(SEARCH_RESULT),
            _FakeResponse(DETAILS_RESULT),
        ]
        key = "2026|Union Square|E 17th St"
        enrich_subject(FARMERS_MARKET, key, "Union Square Greenmarket NY")
        request.side_effect = [
            _FakeResponse(SEARCH_RESULT),
            _FakeResponse(DETAILS_RESULT),
        ]
        enrich_subject(FARMERS_MARKET, key, "Union Square Greenmarket NY")
        self.assertEqual(
            PlaceEnrichment.objects.filter(kind=FARMERS_MARKET, key=key).count(), 1
        )
        self.assertEqual(PlaceReview.objects.count(), 1)


class EnrichPlacesCommandOrderingTests(TestCase):
    databases = {"default", "community"}

    def test_restaurants_prefer_missing_coordinates(self):
        from search.management.commands.enrich_places import Command

        RestaurantInspection.objects.create(
            camis="10",
            dba="Has Coords",
            boro="Brooklyn",
            street="1 Main",
            zipcode="11201",
            inspection_date="2025-01-01",
        )
        RestaurantInspection.objects.create(
            camis="20",
            dba="Missing Coords",
            boro="Queens",
            street="2 Main",
            zipcode="11101",
            inspection_date="2025-01-01",
        )
        PlaceEnrichment.objects.create(
            kind=DOHMH,
            key=dohmh_key("10"),
            camis="10",
            latitude=40.7,
            longitude=-73.9,
        )
        # camis 10 is already enriched — skipped. Only 20 remains; with a
        # second unenriched restaurant that has coords, missing-coords wins.
        RestaurantInspection.objects.create(
            camis="30",
            dba="Also Missing Enrichment But Located",
            boro="Bronx",
            street="3 Main",
            zipcode="10451",
            inspection_date="2025-01-01",
        )
        from community.models import LocationLookup
        from django.utils import timezone

        LocationLookup.objects.create(
            kind=DOHMH,
            key=dohmh_key("30"),
            found=True,
            latitude=40.8,
            longitude=-73.9,
            fetched_at=timezone.now(),
        )

        targets = Command()._restaurant_targets({"refresh": False, "limit": 1})
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["camis"], "20")
