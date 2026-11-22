"""Top picks photos: stored Google photo reference first, fetched once if missing."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from community.models import Restaurant
from nycfood.test_utils import ALL_DATABASES, make_restaurant
from search.services import places
from search.services.places import PlacesAPIError, ensure_photos, forget_photo

FETCH = "search.services.places.fetch_photo_name"
ON = override_settings(GOOGLE_PHOTO_FETCH=True, GOOGLE_PLACES_API_KEY="k")
PHOTO = "places/p1/photos/abc"


@ON
class EnsurePhotosTests(TestCase):
    databases = ALL_DATABASES

    def test_stored_photo_needs_no_request(self):
        make_restaurant("p1", photo_name=PHOTO)
        with patch(FETCH) as fetch:
            self.assertEqual(ensure_photos(["p1"]), {"p1": PHOTO})
        fetch.assert_not_called()

    def test_missing_photo_is_fetched_and_stored(self):
        make_restaurant("p1")
        fetched_at = Restaurant.objects.get(place_id="p1").fetched_at
        with patch(FETCH, return_value=PHOTO) as fetch:
            self.assertEqual(ensure_photos(["p1"]), {"p1": PHOTO})
            self.assertEqual(ensure_photos(["p1"]), {"p1": PHOTO})
        fetch.assert_called_once_with("p1")
        row = Restaurant.objects.get(place_id="p1")
        self.assertEqual(row.photo_name, PHOTO)
        self.assertIsNotNone(row.photo_checked_at)
        self.assertEqual(row.fetched_at, fetched_at)  # not a full refresh

    def test_place_without_photos_is_not_asked_again_for_30_days(self):
        make_restaurant("p1")
        with patch(FETCH, return_value="") as fetch:
            self.assertEqual(ensure_photos(["p1"]), {})
            ensure_photos(["p1"])
        fetch.assert_called_once()

        Restaurant.objects.filter(place_id="p1").update(
            photo_checked_at=timezone.now() - timedelta(days=31)
        )
        with patch(FETCH, return_value=PHOTO) as fetch:
            self.assertEqual(ensure_photos(["p1"]), {"p1": PHOTO})
        fetch.assert_called_once()

    def test_google_failure_is_retried_later(self):
        make_restaurant("p1")
        with patch(FETCH, side_effect=PlacesAPIError("down")):
            self.assertEqual(ensure_photos(["p1"]), {})
        self.assertIsNone(Restaurant.objects.get(place_id="p1").photo_checked_at)
        with patch(FETCH, return_value=PHOTO):
            self.assertEqual(ensure_photos(["p1"]), {"p1": PHOTO})

    def test_off_without_setting_or_key(self):
        make_restaurant("p1")
        for settings in ({"GOOGLE_PHOTO_FETCH": False}, {"GOOGLE_PLACES_API_KEY": ""}):
            with override_settings(**settings), patch(FETCH) as fetch:
                self.assertEqual(ensure_photos(["p1"]), {})
            fetch.assert_not_called()

    def test_fetch_asks_for_photos_only_with_short_timeout(self):
        with patch.object(places, "_request", return_value={}) as request:
            self.assertEqual(places.fetch_photo_name("p1"), "")
        _method, url, mask = request.call_args.args
        self.assertTrue(url.endswith("/places/p1"))
        self.assertEqual(mask, "photos")
        self.assertEqual(request.call_args.kwargs["timeout"], places.PHOTO_TIMEOUT)

    def test_forget_photo_clears_reference(self):
        make_restaurant("p1", photo_name=PHOTO, photo_checked_at=timezone.now())
        forget_photo(PHOTO)
        row = Restaurant.objects.get(place_id="p1")
        self.assertEqual((row.photo_name, row.photo_checked_at), ("", None))


@ON
class TopPicksPhotoTests(TestCase):
    databases = ALL_DATABASES

    def test_home_top_picks_show_fetched_photo(self):
        for i, cuisine in enumerate(["American", "Thai", "Mexican"]):
            make_restaurant(f"p{i}", name=f"Place {i}", cuisine=cuisine)
        with patch(FETCH, side_effect=lambda pid: f"places/{pid}/photos/x") as fetch:
            response = self.client.get(reverse("search:home"))
        picks = response.context["top_picks"]
        self.assertTrue(picks)
        for pick in picks:
            self.assertIn("photo", pick["photo_url"])
            self.assertIn(pick["place_id"], pick["photo_url"])
        self.assertEqual(fetch.call_count, len(picks))  # only the shown picks


class PhotoViewExpiryTests(TestCase):
    databases = ALL_DATABASES

    def test_expired_reference_is_cleared(self):
        make_restaurant("p1", photo_name=PHOTO, photo_checked_at=timezone.now())
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "k"}), patch(
            "restaurants.places.requests.get", return_value=MagicMock(status_code=400)
        ):
            response = self.client.get(reverse("restaurants:photo"), {"name": PHOTO})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Restaurant.objects.get(place_id="p1").photo_name, "")

    def test_other_errors_keep_reference(self):
        make_restaurant("p1", photo_name=PHOTO)
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "k"}), patch(
            "restaurants.places.requests.get", return_value=MagicMock(status_code=500)
        ):
            self.client.get(reverse("restaurants:photo"), {"name": PHOTO})
        self.assertEqual(Restaurant.objects.get(place_id="p1").photo_name, PHOTO)
