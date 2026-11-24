from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from io import StringIO

from django.core.management import call_command

from community.keys import GOOGLE, FARMERS_MARKET, GROCERY, google_key
from community.models import PlaceEnrichment, PlaceReview, Restaurant
from search.services.places import (
    PlacesAPIError,
    enrich_place_id,
    enrich_subject,
    restaurant_fields,
    save_restaurant,
)
from nycfood.test_utils import ALL_DATABASES, make_restaurant


@patch.dict("os.environ", {"GOOGLE_API_KEY": ""})
class RestaurantSearchTests(TestCase):
    databases = ALL_DATABASES

    @classmethod
    def setUpTestData(cls):
        make_restaurant(
            "1",
            "Joe's Pizza",
            boro="Brooklyn",
            street="1 Main St",
            zipcode="11201",
            cuisine="Pizza",
        )
        make_restaurant(
            "3",
            "Green Leaf",
            boro="Manhattan",
            street="3 Main St",
            zipcode="10003",
            cuisine="Vegan",
        )
        make_restaurant(
            "4",
            "Thai Garden",
            boro="Queens",
            street="4 Main St",
            zipcode="11101",
            cuisine="Thai",
        )
        make_restaurant(
            "2",
            "Taco Town",
            boro="Queens",
            street="2 Main St",
            zipcode="11101",
            cuisine="Mexican",
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

    def test_search_result_links_to_the_detail_page(self):
        item = self.get({"q": "pizza"}).context["items"][0]
        self.assertEqual(item["key"], "google:1")
        self.assertEqual(item["url"], reverse("search:restaurant_detail", args=["1"]))

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
        make_restaurant("5", "Fish Shack", cuisine="Seafood")
        self.assertEqual(
            self.names({"diet": "pescatarian"}), ["Fish Shack", "Green Leaf"]
        )

    def test_keto_matches_low_carb_cuisines(self):
        make_restaurant("6", "Prime Cuts", cuisine="Steakhouse")
        self.assertEqual(self.names({"diet": "keto"}), ["Prime Cuts"])

    def test_halal_needs_live_google_results(self):
        response = self.get({"diet": "halal"})
        self.assertContains(response, "Halal is only available with Google Places")
        self.assertEqual(response.context["items"], [])

    def test_avoid_shellfish_excludes_shellfish_heavy_cuisines(self):
        make_restaurant("7", "Oyster Bar", cuisine="Seafood")
        self.assertEqual(
            self.names({"avoid": "shellfish"}),
            ["Green Leaf", "Joe's Pizza", "Taco Town"],
        )

    def test_avoid_nuts_shows_disclaimer(self):
        response = self.get({"avoid": "nuts"})
        self.assertContains(response, "Always confirm allergies with the restaurant.")

    def test_results_show_cuisine(self):
        self.assertContains(self.get({"q": "thai"}), '<div class="result-details">Thai')

    def test_detail_has_no_inspection_history(self):
        response = self.client.get(reverse("search:restaurant_detail", args=["1"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["name"], "Joe's Pizza")
        self.assertNotIn("inspections", response.context)
        self.assertNotContains(response, "Inspection history")

    def test_detail_shows_healthiness_score_breakdown(self):
        response = self.client.get(reverse("search:restaurant_detail", args=["1"]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("healthiness_score", response.context)
        breakdown = response.context["score_breakdown"]
        self.assertIsNotNone(breakdown)
        self.assertTrue(breakdown["parts"])
        self.assertIn(breakdown["confidence"], ("high", "medium", "low"))
        content = response.content.decode()
        self.assertIn("Health score", content)
        self.assertIn("Out of 100", content)
        self.assertIn("See how it", content)
        self.assertIn("hs-track", content)

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

# One Text Search answer that carries every detail field (see places.py).
SEARCH_RESULT = {"places": [DETAILS_RESULT]}


DETAILS_RESULT.update(
    {
        "primaryType": "pizza_restaurant",
        "types": ["pizza_restaurant", "restaurant", "food"],
        "addressComponents": [
            {"longText": "1", "types": ["street_number"]},
            {"longText": "Main Street", "types": ["route"]},
            {"longText": "Brooklyn", "types": ["sublocality_level_1", "sublocality"]},
            {"longText": "11201", "types": ["postal_code"]},
        ],
        "photos": [{"name": "places/ChIJtest/photos/p1"}],
    }
)


@override_settings(GOOGLE_PLACES_API_KEY="test-key")
class EnrichRestaurantTests(TestCase):
    databases = ALL_DATABASES

    @patch("search.services.places.requests.request")
    def test_enrich_saves_restaurant_place_and_reviews(self, request):
        request.return_value = _FakeResponse(DETAILS_RESULT)
        enrichment = enrich_place_id("ChIJtest")
        method, url = request.call_args.args
        self.assertEqual((method, url.rsplit("/", 1)[-1]), ("GET", "ChIJtest"))
        self.assertEqual(enrichment.kind, GOOGLE)
        self.assertEqual(enrichment.key, google_key("ChIJtest"))
        self.assertEqual(enrichment.place_id, "ChIJtest")
        self.assertEqual(enrichment.rating, 4.5)
        self.assertEqual(enrichment.price_level_display, "$")
        self.assertEqual(enrichment.reviews.first().author_name, "Sam")
        restaurant = Restaurant.objects.get(place_id="ChIJtest")
        self.assertEqual(restaurant.name, "Joe's Pizza")
        self.assertEqual(restaurant.cuisine, "Pizza")
        self.assertEqual(restaurant.boro, "Brooklyn")
        self.assertEqual(restaurant.street, "1 Main Street")
        self.assertEqual(restaurant.zipcode, "11201")
        self.assertEqual(restaurant.price, "$")
        self.assertEqual(restaurant.photo_name, "places/ChIJtest/photos/p1")
        self.assertTrue(restaurant.shuffle_seed)

    @patch("search.services.places.requests.request")
    def test_refetch_replaces_reviews(self, request):
        request.return_value = _FakeResponse(DETAILS_RESULT)
        enrich_place_id("ChIJtest")
        enrich_place_id("ChIJtest")
        self.assertEqual(PlaceEnrichment.objects.count(), 1)
        self.assertEqual(PlaceReview.objects.count(), 1)
        self.assertEqual(Restaurant.objects.count(), 1)

    @patch("search.services.places.requests.request")
    def test_api_error_raises(self, request):
        request.return_value = _FakeResponse(
            {"error": {"message": "denied"}}, status_code=403
        )
        with self.assertRaises(PlacesAPIError):
            enrich_place_id("ChIJtest")

    @override_settings(GOOGLE_PLACES_API_KEY="")
    def test_missing_key_raises(self):
        with self.assertRaises(PlacesAPIError):
            enrich_place_id("ChIJtest")


class SaveRestaurantTests(TestCase):
    databases = ALL_DATABASES

    def test_generic_types_keep_the_stored_cuisine(self):
        make_restaurant("ChIJtest", "Joe's", cuisine="Pizza")
        save_restaurant({**DETAILS_RESULT, "primaryType": "restaurant", "types": []})
        self.assertEqual(Restaurant.objects.get(place_id="ChIJtest").cuisine, "Pizza")

    def test_borough_falls_back_to_the_zip_code(self):
        fields = restaurant_fields(
            {"formattedAddress": "5 Ave, Queens, NY 11372", "addressComponents": []}
        )
        self.assertEqual((fields["zipcode"], fields["boro"]), ("11372", "Queens"))

    def test_outside_nyc_has_no_borough(self):
        fields = restaurant_fields({"formattedAddress": "1 Rd, Hoboken, NJ 07030"})
        self.assertEqual(fields["boro"], "")


def _place(place_id, boro="Queens", zipcode="11101", **extra):
    return {
        "id": place_id,
        "displayName": {"text": f"Place {place_id}"},
        "formattedAddress": f"1 St, {boro}, NY {zipcode}",
        "addressComponents": [{"longText": boro, "types": ["sublocality_level_1"]}],
        "types": ["thai_restaurant"],
        "rating": 4.3,
        **extra,
    }


@override_settings(GOOGLE_PLACES_API_KEY="test-key")
class SyncRestaurantsCommandTests(TestCase):
    databases = ALL_DATABASES

    def run_command(self, *args):
        out = StringIO()
        call_command("sync_restaurants", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    @patch("search.services.places.requests.request")
    def test_discovery_follows_pages_and_skips_places_outside_nyc(self, request):
        request.side_effect = [
            _FakeResponse(
                {
                    "places": [
                        _place("a"),
                        _place("b", boro="Hoboken", zipcode="07030"),
                    ],
                    "nextPageToken": "next",
                }
            ),
            _FakeResponse({"places": [_place("c")]}),
        ]
        out = self.run_command(
            "--discover-only", "--boro", "Queens", "--term", "thai", "--pages", "3"
        )
        self.assertEqual(request.call_count, 2)
        body = request.call_args_list[1].kwargs["json"]
        self.assertEqual(body["pageToken"], "next")
        self.assertEqual(body["textQuery"], "thai in Queens, NY")
        self.assertEqual(
            sorted(Restaurant.objects.values_list("place_id", flat=True)), ["a", "c"]
        )
        self.assertEqual(Restaurant.objects.get(place_id="a").cuisine, "Thai")
        self.assertIn("Added 2", out)

    @patch("search.services.places.requests.request")
    def test_limit_caps_google_requests(self, request):
        request.return_value = _FakeResponse({"places": [_place("a")]})
        self.run_command("--discover-only", "--boro", "Queens", "--limit", "2")
        self.assertEqual(request.call_count, 2)

    @patch("search.services.places.requests.request")
    def test_refresh_only_refetches_stale_rows(self, request):
        from datetime import timedelta

        from django.utils import timezone

        make_restaurant("ChIJtest", "Old")
        make_restaurant("fresh", "New")
        Restaurant.objects.filter(place_id="ChIJtest").update(
            fetched_at=timezone.now() - timedelta(days=40)
        )
        request.return_value = _FakeResponse(DETAILS_RESULT)
        self.run_command("--refresh-only")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(
            Restaurant.objects.get(place_id="ChIJtest").name, "Joe's Pizza"
        )

    @patch("search.services.places.requests.request")
    def test_dry_run_makes_no_requests(self, request):
        out = self.run_command("--dry-run", "--boro", "Bronx", "--term", "pizza")
        request.assert_not_called()
        self.assertIn("pizza in Bronx, NY", out)


class RestaurantDetailGoogleTests(TestCase):
    databases = ALL_DATABASES

    @classmethod
    def setUpTestData(cls):
        make_restaurant(
            "1", "Joe's Pizza", boro="Brooklyn", street="1 Main St", zipcode="11201"
        )

    def test_detail_shows_stored_google_data(self):
        place = PlaceEnrichment.objects.create(
            kind=GOOGLE,
            key=google_key("1"),
            place_id="1",
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
        # Google data (rating, reviews) is stored and feeds the score, but the
        # page no longer shows a Google data panel; the Menu box instead.
        self.assertEqual(response.context["place"], place)
        self.assertNotContains(response, "Google data")
        self.assertNotContains(response, "Great slice.")
        self.assertContains(response, 'id="what-to-order"')

    def test_detail_without_google_data_has_no_panel(self):
        response = self.client.get(reverse("search:restaurant_detail", args=["1"]))
        self.assertNotContains(response, "No Google data stored yet")
        self.assertNotContains(response, "Get Google data")

    @patch("search.views.enrich_place_id")
    def test_refresh_post_enriches_and_redirects(self, enrich):
        response = self.client.post(reverse("search:refresh_place", args=["1"]))
        self.assertRedirects(response, reverse("search:restaurant_detail", args=["1"]))
        enrich.assert_called_once_with("1")

    @patch("search.views.enrich_place_id", side_effect=PlacesAPIError("boom"))
    def test_refresh_post_reports_error(self, enrich):
        response = self.client.post(
            reverse("search:refresh_place", args=["1"]), follow=True
        )
        self.assertContains(response, "Could not fetch Google data")

    def test_refresh_get_not_allowed(self):
        response = self.client.get(reverse("search:refresh_place", args=["1"]))
        self.assertEqual(response.status_code, 405)


class HomeTopPicksTests(TestCase):
    databases = ALL_DATABASES

    def review(self, place_id, text, author="Tester"):
        place = PlaceEnrichment.objects.create(
            kind=GOOGLE, key=google_key(place_id), place_id=place_id
        )
        PlaceReview.objects.create(
            place=place,
            text=text,
            author_name=author,
            rating=5,
            relative_time="2 weeks ago",
        )

    def test_home_page_shows_top_picks_with_google_review(self):
        make_restaurant(
            "999",
            "Thai Garden",
            address="4 Main St, Queens, NY 11101",
            boro="Queens",
            cuisine="Thai",
            rating=4.8,
            rating_count=150,
            price_level="PRICE_LEVEL_MODERATE",
            photo_name="places/ChIJ123/photos/abc",
        )
        self.review("999", "Best pad thai in Queens! Must try.", "Alice M.")
        with patch("search.views.enrich_place_id") as fetch:
            response = self.client.get(reverse("search:home"))
        fetch.assert_not_called()  # stored Google data only
        self.assertEqual(response.status_code, 200)
        first_pick = response.context["top_picks"][0]
        self.assertEqual(
            first_pick["review"]["text"], "Best pad thai in Queens! Must try."
        )
        self.assertEqual(first_pick["review"]["author_name"], "Alice M.")
        self.assertEqual(first_pick["google"]["price"], "$$")
        self.assertIn("reason_tags", first_pick)
        expected_photo = "restaurants/photo/?name=places%2FChIJ123%2Fphotos%2Fabc"
        self.assertIn(expected_photo, first_pick["photo_url"])
        content = response.content.decode("utf-8")
        self.assertIn("Best pad thai in Queens! Must try.", content)
        self.assertIn("Alice M.", content)
        self.assertIn(expected_photo, content)
        self.assertIn('href="/restaurant/999/?from=home"', content)

    def test_top_picks_are_score_ordered(self):
        for place_id, name, cuisine, text in (
            ("901", "Slice House", "Pizza", "greasy fried salty"),
            ("902", "Green Bowl", "Salads", "fresh healthy salad grilled organic"),
            ("903", "McDonald's Midtown", "Hamburgers", "greasy fried salty"),
        ):
            make_restaurant(place_id, name, cuisine=cuisine, rating=4.0)
            self.review(place_id, text)
        response = self.client.get(reverse("search:home"))
        names = [pick["name"] for pick in response.context["top_picks"]]
        self.assertEqual(names[0], "Green Bowl")
        scores = [pick["score"] for pick in response.context["top_picks"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


@override_settings(GOOGLE_PLACES_API_KEY="test-key")
class EnrichSubjectTests(TestCase):
    databases = ALL_DATABASES

    @patch("search.services.places.requests.request")
    def test_enrich_grocery_saves_kind_key_and_reviews(self, request):
        request.return_value = _FakeResponse(SEARCH_RESULT)
        key = "Healthy Corner|100 Main St|11201"
        enrichment = enrich_subject(
            GROCERY, key, "Healthy Corner 100 Main St Brooklyn NY 11201"
        )
        self.assertEqual(enrichment.kind, GROCERY)
        self.assertEqual(enrichment.key, key)
        self.assertEqual(enrichment.reviews.count(), 1)
        self.assertFalse(Restaurant.objects.exists())  # only restaurants go there

    @patch("search.services.places.requests.request")
    def test_one_request_asks_for_every_detail_field(self, request):
        request.return_value = _FakeResponse(SEARCH_RESULT)
        enrich_subject(GROCERY, "k", "Healthy Corner NY")
        self.assertEqual(request.call_count, 1)
        method, url = request.call_args.args
        mask = request.call_args.kwargs["headers"]["X-Goog-FieldMask"].split(",")
        self.assertEqual(
            (method, url.rsplit("/", 1)[-1]), ("POST", "places:searchText")
        )
        for field in ("places.id", "places.reviews", "places.reviewSummary"):
            self.assertIn(field, mask)

    @patch("search.services.places.requests.request")
    def test_no_match_is_an_error(self, request):
        request.return_value = _FakeResponse({"places": []})
        with self.assertRaises(PlacesAPIError):
            enrich_subject(GROCERY, "k", "Nowhere NY")

    @patch("search.services.places.requests.request")
    def test_enrich_market_refresh_replaces_reviews(self, request):
        request.return_value = _FakeResponse(SEARCH_RESULT)
        key = "2026|Union Square|E 17th St"
        enrich_subject(FARMERS_MARKET, key, "Union Square Greenmarket NY")
        enrich_subject(FARMERS_MARKET, key, "Union Square Greenmarket NY")
        self.assertEqual(
            PlaceEnrichment.objects.filter(kind=FARMERS_MARKET, key=key).count(), 1
        )
        self.assertEqual(PlaceReview.objects.count(), 1)
