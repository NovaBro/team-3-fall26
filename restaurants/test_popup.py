from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse

from restaurants import places


class PlaceFieldsTests(SimpleTestCase):
    def test_field_mask_asks_for_rating_and_photos(self):
        for field in ("places.rating", "places.userRatingCount", "places.photos"):
            self.assertIn(field, places.FIELD_MASK)

    def test_normalize_reads_rating_and_first_photo(self):
        out = places._normalize({
            "rating": 4.5, "userRatingCount": 120,
            "photos": [{"name": "places/abc/photos/xyz"}, {"name": "places/abc/photos/two"}],
        })
        self.assertEqual((out["rating"], out["rating_count"], out["photo"]), (4.5, 120, "places/abc/photos/xyz"))

    def test_normalize_without_rating_or_photos(self):
        out = places._normalize({})
        self.assertEqual((out["rating"], out["rating_count"], out["photo"]), (None, None, ""))


class PhotoUrlTests(SimpleTestCase):
    name = "places/abc/photos/xyz"

    def test_returns_photo_uri_and_keeps_key_in_header(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"photoUri": "https://img.example/p.jpg"}
        with patch("restaurants.places.requests.get", return_value=resp) as get:
            self.assertEqual(places.get_photo_url(self.name, api_key="k"), "https://img.example/p.jpg")
        self.assertEqual(get.call_args.kwargs["headers"]["X-Goog-Api-Key"], "k")
        self.assertNotIn("key", get.call_args.kwargs["params"])

    def test_rejects_bad_names_without_calling_google(self):
        with patch("restaurants.places.requests.get") as get:
            for bad in ("", "../x", "places/a/photos/b/../../c", "http://evil"):
                self.assertEqual(places.get_photo_url(bad, api_key="k"), "")
        get.assert_not_called()

    def test_no_key_returns_empty(self):
        with patch.dict("os.environ", {"GOOGLE_API_KEY": ""}):
            self.assertEqual(places.get_photo_url(self.name), "")

    def test_google_error_returns_empty(self):
        with patch("restaurants.places.requests.get", return_value=MagicMock(status_code=403)):
            self.assertEqual(places.get_photo_url(self.name, api_key="k"), "")
        with patch("restaurants.places.requests.get", side_effect=places.requests.RequestException()):
            self.assertEqual(places.get_photo_url(self.name, api_key="k"), "")


class PhotoViewTests(SimpleTestCase):
    url = reverse("restaurants:photo")

    def test_redirects_to_the_image(self):
        with patch("restaurants.views.get_photo_url", return_value="https://img.example/p.jpg"):
            resp = self.client.get(self.url, {"name": "places/a/photos/b"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "https://img.example/p.jpg")
        self.assertIn("max-age", resp["Cache-Control"])

    def test_404_when_no_photo(self):
        with patch("restaurants.views.get_photo_url", return_value=""):
            self.assertEqual(self.client.get(self.url, {"name": "x"}).status_code, 404)


class MapPointTests(SimpleTestCase):
    url = reverse("restaurants:search")
    base = {"name": "P", "address": "1 Main St", "price": "$$", "vegetarian": None,
            "lat": 40.7, "lng": -74.0, "maps_url": "https://maps.example/p", "distance_mi": None}

    def _point(self, place):
        with patch("restaurants.views.get_restaurants", return_value=[place]), \
             patch("restaurants.views.attach_inspections", side_effect=lambda x: x):
            resp = self.client.get(self.url, {"area": "Queens"})
        return resp.context["map_points"][0]

    def test_point_has_rating_photo_and_grade_link(self):
        pt = self._point({**self.base, "rating": 4.4, "rating_count": 50, "photo": "places/a/photos/b",
                          "inspection": {"camis": "123", "grade": "A", "date": None}})
        self.assertEqual((pt["rating"], pt["rating_count"], pt["grade"]), (4.4, 50, "A"))
        self.assertTrue(pt["has_inspection"])
        self.assertEqual(pt["detail_url"], reverse("search:restaurant_detail", args=["123"]))
        self.assertTrue(pt["photo_url"].startswith(reverse("restaurants:photo") + "?name=places%2Fa%2Fphotos%2Fb"))

    def test_point_without_extras_is_still_valid(self):
        pt = self._point(dict(self.base))
        self.assertEqual((pt["rating"], pt["photo_url"], pt["detail_url"], pt["grade"]), (None, "", "", ""))
        self.assertFalse(pt["has_inspection"])
