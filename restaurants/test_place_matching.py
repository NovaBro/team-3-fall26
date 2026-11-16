"""Matching an NYC inspection record to its Google place (homepage cards).

GOOGLE_MAPS_JS_KEY=dummy python manage.py test restaurants.test_place_matching
"""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from restaurants.places import _match_street, find_restaurant_place


def google_place(name, number, route, zipcode, rating=4.6):
    return {
        "displayName": {"text": name},
        "formattedAddress": f"{number} {route}, New York, NY {zipcode}, USA",
        "addressComponents": [
            {"longText": number, "types": ["street_number"]},
            {"longText": route, "types": ["route"]},
            {"longText": zipcode, "types": ["postal_code"]},
        ],
        "rating": rating,
        "userRatingCount": 120,
    }


def answer(*places):
    response = MagicMock(status_code=200)
    response.json.return_value = {"places": list(places)}
    return response


class MatchStreetTests(SimpleTestCase):
    def test_dohmh_street_keeps_its_leading_number(self):
        self.assertEqual(_match_street("3 AVENUE", has_number=False), "3 ave")
        self.assertEqual(_match_street("1385 3rd Avenue"), "3 ave")

    def test_ordinals_match_plain_numbers(self):
        self.assertEqual(
            _match_street("WEST   35 STREET", has_number=False),
            _match_street("12 West 35th Street"),
        )

    def test_named_streets_unchanged(self):
        self.assertEqual(_match_street("BROADWAY", has_number=False), "broadway")
        self.assertEqual(_match_street("1 Broadway"), "broadway")


@patch("restaurants.places.requests.post")
class FindRestaurantPlaceTests(SimpleTestCase):
    def find(self, name, zipcode, street):
        return find_restaurant_place(name, zipcode, street, api_key="k")

    def test_numbered_avenue_with_longer_google_name(self, post):
        post.return_value = answer(
            google_place("Oakberry Acai", "1385", "3rd Avenue", "10075")
        )
        place = self.find("OAKBERRY", "10075", "3 AVENUE")
        self.assertIsNotNone(place)
        self.assertEqual(place["rating"], 4.6)

    def test_ordinal_street(self, post):
        post.return_value = answer(
            google_place("Kyma Hudson Yards", "445", "West 35th Street", "10001")
        )
        self.assertIsNotNone(self.find("KYMA", "10001", "WEST 35 STREET"))

    def test_other_street_is_not_a_match(self, post):
        post.return_value = answer(
            google_place("Oakberry Acai", "200", "Lexington Avenue", "10075")
        )
        self.assertIsNone(self.find("OAKBERRY", "10075", "3 AVENUE"))


@override_settings(PLACES_CACHE_SECONDS=3600)
@patch("restaurants.places.requests.post")
class PlaceCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def find(self):
        return find_restaurant_place("OAKBERRY", "10075", "3 AVENUE", api_key="k")

    def test_match_is_remembered(self, post):
        post.return_value = answer(
            google_place("Oakberry Acai", "1385", "3rd Avenue", "10075")
        )
        first = self.find()
        second = self.find()
        self.assertEqual(first, second)
        self.assertEqual(post.call_count, 1)

    def test_no_match_is_remembered(self, post):
        post.return_value = answer()
        self.assertIsNone(self.find())
        self.assertIsNone(self.find())
        self.assertEqual(post.call_count, 1)

    def test_failed_request_is_tried_again(self, post):
        post.return_value = MagicMock(status_code=500)
        self.assertIsNone(self.find())
        post.return_value = answer(
            google_place("Oakberry Acai", "1385", "3rd Avenue", "10075")
        )
        self.assertIsNotNone(self.find())
        self.assertEqual(post.call_count, 2)

    @override_settings(PLACES_CACHE_SECONDS=0)
    def test_off_when_zero(self, post):
        post.return_value = answer()
        self.find()
        self.find()
        self.assertEqual(post.call_count, 2)
