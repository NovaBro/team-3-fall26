"""Tests for the Find food page (issue #109): one page for farmers markets,
grocery stores and restaurants, with missing locations looked up on Google."""

from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from community.models import LocationLookup, PlaceEnrichment
from restaurants.places import PlacesError, locate_place
from search.find_food import Chain, market_operates_on_day
from search.models import FarmersMarket, HealthyStore, RestaurantInspection

NO_KEY = {"GOOGLE_API_KEY": ""}
WITH_KEY = {"GOOGLE_API_KEY": "test-key"}


def found(lat=40.7, lng=-73.9, address="1 Found St, New York, NY 10001"):
    return {"id": "ChIJfound", "address": address, "lat": lat, "lng": lng}


class FindFoodData(TestCase):
    databases = {"default", "community"}

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
            accepts_ebt="Yes",
        )
        FarmersMarket.objects.create(
            year=2026,
            market_name="Saratoga Farm Stand",
            borough="Brooklyn",
            street_address="1965-1971 Fulton St.",
            latitude=40.68,
            longitude=-0.00008,
            days_of_operation="Tuesday-Saturday",
        )
        FarmersMarket.objects.create(
            year=2026, market_name="Market Without Coordinates", borough="Queens"
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
            store_name="Uptown Grocer",
            street_address="5 Broadway",
            borough="New York",
            zip_code="10040",
        )
        RestaurantInspection.objects.create(
            camis="1",
            dba="Joe's Pizza",
            boro="Brooklyn",
            street="1 Main St",
            zipcode="11201",
            cuisine="Pizza",
            inspection_date="2025-01-01",
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
            grade="B",
        )
        PlaceEnrichment.objects.create(
            camis="1",
            place_id="ChIJtest",
            display_name="Joe's Pizza",
            formatted_address="1 Main St, Brooklyn, NY 11201",
            latitude=40.695,
            longitude=-73.985,
        )

    def get(self, params=None):
        return self.client.get(reverse("search:index"), params or {})

    def items(self, params=None):
        return {item["name"]: item for item in self.get(params).context["items"]}


@patch.dict("os.environ", NO_KEY)
class FindFoodPageTests(FindFoodData):
    def test_one_nav_tab_replaces_the_old_five(self):
        response = self.get()
        self.assertContains(response, ">Find food</a>")
        for gone in ("Explore datasets", "Farmers market</a>", "Combined map"):
            self.assertNotContains(response, gone)
        self.assertNotContains(response, ">Find restaurants</a>")

    def test_landing_shows_every_store_type_on_the_map(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "maplibre-gl@5.6.1/dist/maplibre-gl.js")
        self.assertContains(response, "combined_map.js")
        self.assertContains(response, 'id="filter-form"')
        for value in ("restaurant", "farmers_market", "grocery"):
            self.assertContains(
                response, f'type="checkbox" name="types" value="{value}"'
            )
        self.assertContains(response, 'value="inspections"')
        categories = {p["category"] for p in response.context["map_points"]}
        self.assertEqual(categories, {"farmers_market", "grocery", "restaurant_dohmh"})
        self.assertEqual(
            response.context["counts"],
            {"restaurant": 2, "farmers_market": 3, "grocery": 2},
        )

    def test_map_points_keep_community_keys_and_links(self):
        points = {p["name"]: p for p in self.get().context["map_points"]}
        self.assertEqual(
            points["Union Square Greenmarket"]["key"],
            "2026|Union Square Greenmarket|E 17th St",
        )
        self.assertEqual(
            points["Healthy Corner"]["key"], "Healthy Corner|100 Main St|11201"
        )
        self.assertEqual(points["Joe's Pizza"]["key"], "camis:1")
        self.assertEqual(
            points["Joe's Pizza"]["url"],
            reverse("search:restaurant_detail", args=["1"]),
        )
        # No coordinates anywhere and no Google key: listed, but not mapped.
        self.assertNotIn("Market Without Coordinates", points)
        self.assertNotIn("Taco Town", points)

    def test_unlocated_rows_are_listed_with_a_note(self):
        response = self.get({"types": "farmers_market"})
        self.assertIn(
            "Market Without Coordinates", self.items({"types": "farmers_market"})
        )
        self.assertContains(response, "Location not found")

    def test_restaurant_coordinates_come_from_enrichment(self):
        joe = self.items({"types": "restaurant"})["Joe's Pizza"]
        self.assertEqual((joe["lat"], joe["lng"]), (40.695, -73.985))
        self.assertEqual(joe["grade"], "A")

    def test_farmers_markets_use_latest_year_and_saratoga_fix(self):
        items = self.items({"types": "farmers_market"})
        self.assertNotIn("Older Market Listing", items)
        saratoga = items["Saratoga Farm Stand"]
        self.assertEqual(saratoga["address"], "1965 Fulton St, Brooklyn, NY 11233")
        self.assertEqual((saratoga["lat"], saratoga["lng"]), (40.6785, -73.916194))
        self.assertIn("Accepts EBT", items["Union Square Greenmarket"]["details"])

    def test_market_day_filter(self):
        items = self.items({"types": "farmers_market", "day": "Wednesday"})
        self.assertEqual(list(items), ["Saratoga Farm Stand"])

    def test_zip_filter_applies_to_every_type(self):
        items = self.items({"zip": "11201"})
        self.assertEqual(set(items), {"Joe's Pizza", "Healthy Corner"})
        self.assertEqual(
            list(self.items({"zip": "11233", "types": "farmers_market"})),
            ["Saratoga Farm Stand"],
        )

    def test_borough_filter_and_new_york_means_manhattan(self):
        self.assertEqual(
            set(self.items({"area": "Brooklyn"})),
            {"Joe's Pizza", "Saratoga Farm Stand", "Healthy Corner"},
        )
        manhattan = self.items({"area": "Manhattan", "types": "grocery"})
        self.assertEqual(list(manhattan), ["Uptown Grocer"])
        self.assertEqual(manhattan["Uptown Grocer"]["borough"], "Manhattan")

    def test_name_filter_and_store_types(self):
        self.assertEqual(list(self.items({"q": "healthy"})), ["Healthy Corner"])
        self.assertEqual(
            set(self.items({"types": ["grocery", "restaurant"], "area": "Brooklyn"})),
            {"Joe's Pizza", "Healthy Corner"},
        )

    def test_restaurant_filters_leave_other_types_alone(self):
        items = self.items({"grade": "B", "area": "Queens"})
        self.assertEqual(set(items), {"Taco Town", "Market Without Coordinates"})

    def test_distance_narrows_markets_and_notes_inspection_records(self):
        params = {"lat": "40.737", "lng": "-73.99", "distance": "1"}
        response = self.get(params)
        names = {item["name"] for item in response.context["items"]}
        self.assertIn("Union Square Greenmarket", names)
        self.assertNotIn("Saratoga Farm Stand", names)
        self.assertContains(response, "Distance only narrows farmers markets")
        self.assertContains(response, "Using your location")
        self.assertContains(response, 'id="clear-location"')

    def test_google_only_filters_are_ignored_for_inspection_records(self):
        with patch("search.find_food.get_restaurants") as google:
            response = self.get({"price": "$$", "types": "restaurant"})
        google.assert_not_called()
        self.assertContains(response, "only apply to Google Places results")
        self.assertEqual(len(response.context["items"]), 2)

    def test_invalid_filter_shows_error(self):
        response = self.get({"zip": "abc"})
        self.assertContains(response, "Please fix these filters")
        self.assertContains(response, "Enter up to 5 digits")
        self.assertEqual(response.context["items"], [])

    def test_kosher_needs_inspection_records(self):
        response = self.get({"source": "google", "diet": "kosher"})
        self.assertContains(response, "Kosher is only available with NYC inspection")

    def test_pagination_spans_store_types(self):
        for n in range(30):
            RestaurantInspection.objects.create(camis=f"x{n}", dba=f"Aaa {n:02}")
        first = self.get()
        self.assertEqual(len(first.context["items"]), 25)
        self.assertEqual(first.context["total"], 37)
        second = self.get({"page": "2"}).context["items"]
        kinds = {item["kind"] for item in second}
        self.assertEqual(len(second), 12)
        self.assertEqual(kinds, {"restaurant_dohmh", "farmers_market", "grocery"})


@patch.dict("os.environ", WITH_KEY)
class MissingLocationLookupTests(FindFoodData):
    @patch("search.locations.locate_place", return_value=found())
    def test_missing_location_is_looked_up_and_cached(self, locate):
        item = self.items({"types": "grocery"})["Uptown Grocer"]
        self.assertEqual((item["lat"], item["lng"]), (40.7, -73.9))
        self.assertEqual(item["location_source"], "google")
        locate.assert_called_once_with("Uptown Grocer 5 Broadway New York NY 10040")
        row = LocationLookup.objects.get(kind="grocery")
        self.assertTrue(row.found)
        self.assertEqual(row.place_id, "ChIJfound")

        locate.reset_mock()
        response = self.get({"types": "grocery"})
        locate.assert_not_called()
        self.assertIn(
            "Uptown Grocer", {p["name"] for p in response.context["map_points"]}
        )
        self.assertContains(response, "Located via Google")

    @patch("search.locations.locate_place", return_value=found())
    def test_restaurants_without_coordinates_are_looked_up(self, locate):
        taco = self.items({"types": "restaurant"})["Taco Town"]
        self.assertEqual(taco["lat"], 40.7)
        # Joe's Pizza already had enrichment coordinates: one call only.
        locate.assert_called_once_with("Taco Town 2 Main St Queens NY 11101")

    @patch("search.locations.locate_place", return_value=found())
    def test_cached_restaurants_show_on_map_beyond_the_current_page(self, _locate):
        LocationLookup.objects.create(
            kind="restaurant_dohmh",
            key="camis:2",
            found=True,
            latitude=40.75,
            longitude=-73.86,
        )
        for n in range(30):
            RestaurantInspection.objects.create(camis=f"x{n}", dba=f"Aaa {n:02}")
        response = self.get({"types": "restaurant", "page": "1"})
        names = {item["name"] for item in response.context["items"]}
        self.assertNotIn("Taco Town", names)
        self.assertIn("Taco Town", {p["name"] for p in response.context["map_points"]})

    @patch("search.locations.locate_place", return_value=None)
    def test_misses_are_cached_too(self, locate):
        self.items({"types": "grocery"})
        self.items({"types": "grocery"})
        self.assertEqual(locate.call_count, 1)
        self.assertFalse(LocationLookup.objects.get(kind="grocery").found)

    @patch("search.locations.locate_place", side_effect=PlacesError("down"))
    def test_google_errors_are_not_cached(self, locate):
        item = self.items({"types": "grocery"})["Uptown Grocer"]
        self.assertIsNone(item["lat"])
        self.assertFalse(LocationLookup.objects.exists())

    @patch("search.locations.locate_place", return_value=found(lat=40.8))
    def test_lookups_older_than_30_days_are_refreshed(self, locate):
        row = LocationLookup.objects.create(
            kind="grocery",
            key="Uptown Grocer|5 Broadway|10040",
            found=True,
            latitude=40.6,
            longitude=-73.9,
        )
        LocationLookup.objects.filter(pk=row.pk).update(
            fetched_at=timezone.now() - timedelta(days=31)
        )
        item = self.items({"types": "grocery"})["Uptown Grocer"]
        self.assertEqual(item["lat"], 40.8)
        locate.assert_called_once()

    @patch("search.locations.locate_place", return_value=found())
    def test_locate_places_command(self, locate):
        out = StringIO()
        call_command("locate_places", "--type", "grocery", stdout=out)
        self.assertIn("grocery: 1 Google lookups", out.getvalue())
        self.assertTrue(LocationLookup.objects.get(kind="grocery").found)

    def test_locate_places_command_needs_key(self):
        from django.core.management.base import CommandError

        with patch.dict("os.environ", NO_KEY), self.assertRaises(CommandError):
            call_command("locate_places", stdout=StringIO())


GOOGLE_PLACE = {
    "id": "ChIJlive",
    "name": "Live Spot",
    "address": "123 Ave A, New York, NY 10009",
    "zipcode": "10009",
    "price": "$$",
    "vegetarian": True,
    "lat": 40.73,
    "lng": -73.98,
    "maps_url": "https://maps.google.com/?cid=9",
    "distance_mi": 0.3,
    "rating": 4.4,
    "rating_count": 50,
    "photo": "places/a/photos/b",
}


@patch.dict("os.environ", NO_KEY)
@patch("search.find_food.attach_inspections", side_effect=lambda places: places)
@patch("search.find_food.get_restaurants")
class GooglePlacesSourceTests(FindFoodData):
    def google(self, params):
        return self.get({"types": "restaurant", "source": "google", **params})

    def test_filters_are_passed_together(self, google, _attach):
        google.return_value = []
        self.google(
            {
                "area": "Manhattan",
                "price": ["$", "$$"],
                "diet": "vegan",
                "distance": "1",
                "lat": "40.73",
                "lng": "-73.99",
                "open_now": "on",
                "min_rating": "4",
                "avoid": "nuts",
                "cuisine": "Thai",
            }
        )
        google.assert_called_once_with(
            cuisine="Thai",
            area="Manhattan",
            prices=["$", "$$"],
            diet="vegan",
            lat=40.73,
            lng=-73.99,
            radius_m=1609.344,
            avoid=["nuts"],
            open_now=True,
            min_rating=4.0,
        )

    def test_results_are_shown_with_google_details(self, google, _attach):
        google.return_value = [
            {**GOOGLE_PLACE, "inspection": {"camis": "1", "grade": "A", "date": None}}
        ]
        response = self.google({"area": "Manhattan"})
        item = response.context["items"][0]
        self.assertEqual(item["key"], "google:ChIJlive")
        self.assertEqual(item["category"], "restaurant_google")
        self.assertEqual(
            item["grade_url"], reverse("search:restaurant_detail", args=["1"])
        )
        self.assertTrue(item["photo_url"].startswith(reverse("restaurants:photo")))
        self.assertContains(response, "Live Spot")
        self.assertContains(response, "0.30 mi away")
        self.assertContains(response, "★ 4.4 (50)")
        self.assertContains(response, "Inspection A")
        self.assertEqual(
            [p["category"] for p in response.context["map_points"]],
            ["restaurant_google"],
        )

    def test_name_zip_and_grade_filter_google_results(self, google, _attach):
        google.return_value = [dict(GOOGLE_PLACE)]
        self.assertEqual(len(self.google({"q": "live"}).context["items"]), 1)
        self.assertEqual(self.google({"q": "other"}).context["items"], [])
        self.assertEqual(self.google({"zip": "112"}).context["items"], [])
        self.assertEqual(self.google({"grade": "A"}).context["items"], [])
        self.assertContains(self.google({}), "No inspection data")

    def test_data_source_error_is_shown(self, google, _attach):
        google.side_effect = PlacesError("boom")
        response = self.get({"source": "google"})
        self.assertContains(response, "boom")
        # Markets and grocery still show when Google fails.
        self.assertIn("Healthy Corner", {i["name"] for i in response.context["items"]})


class RedirectTests(TestCase):
    def assertRedirectsTo(self, path, target):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], target)

    def test_old_tabs_redirect_to_find_food(self):
        self.assertRedirectsTo("/restaurants/", "/")
        self.assertRedirectsTo(
            "/restaurants/?area=Queens", "/?area=Queens&types=restaurant&source=google"
        )
        self.assertRedirectsTo("/combined-map/?q=x", "/?q=x")
        self.assertRedirectsTo("/farmers-markets/", "/?types=farmers_market")
        self.assertRedirectsTo("/explore/", "/")
        self.assertRedirectsTo("/explore/menu-items/", "/")


class ChainTests(SimpleTestCase):
    def test_slices_across_segments(self):
        chain = Chain(([1, 2, 3], lambda x: x * 10), ([4, 5], str))
        self.assertEqual(len(chain), 5)
        self.assertEqual(chain[2:4], [30, "4"])
        self.assertEqual(chain[0:10], [10, 20, 30, "4", "5"])
        self.assertEqual(chain[4], "5")


class MarketDayTests(SimpleTestCase):
    def test_ranges_and_lists(self):
        self.assertTrue(market_operates_on_day("Tuesday-Saturday", "Thursday"))
        self.assertFalse(market_operates_on_day("Tuesday-Saturday", "Sunday"))
        self.assertTrue(market_operates_on_day("Wed, Sat", "Saturday"))
        self.assertTrue(market_operates_on_day("Fri - Mon", "Sunday"))
        self.assertFalse(market_operates_on_day("", "Monday"))


def _response(status=200, data=None):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = data or {}
    return response


@patch("restaurants.places.requests.post")
class LocatePlaceTests(SimpleTestCase):
    def test_returns_top_match(self, post):
        post.return_value = _response(
            data={
                "places": [
                    {
                        "id": "abc",
                        "formattedAddress": "5 Broadway, New York, NY",
                        "location": {"latitude": 40.8, "longitude": -73.9},
                    }
                ]
            }
        )
        self.assertEqual(
            locate_place("Uptown Grocer", api_key="k"),
            {
                "id": "abc",
                "address": "5 Broadway, New York, NY",
                "lat": 40.8,
                "lng": -73.9,
            },
        )
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["maxResultCount"], 1)
        self.assertIn("locationRestriction", body)
        self.assertEqual(post.call_args.kwargs["headers"]["X-Goog-Api-Key"], "k")

    def test_no_match_returns_none(self, post):
        post.return_value = _response(data={})
        self.assertIsNone(locate_place("Nowhere", api_key="k"))

    def test_http_error_raises(self, post):
        post.return_value = _response(status=403)
        with self.assertRaises(PlacesError):
            locate_place("x", api_key="k")

    def test_missing_key_raises(self, post):
        with patch.dict("os.environ", NO_KEY), self.assertRaises(PlacesError):
            locate_place("x")
        post.assert_not_called()
