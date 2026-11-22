"""User location pin for distance-aware ranking."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from search.user_location import (
    clear_user_latlng,
    parse_latlng,
    save_user_latlng,
    user_latlng,
)
from nycfood.test_utils import ALL_DATABASES, make_restaurant


class ParseLatLngTests(TestCase):
    def test_accepts_nyc(self):
        self.assertEqual(parse_latlng("40.7128", "-74.0060"), (40.7128, -74.0060))

    def test_rejects_outside_nyc(self):
        with self.assertRaises(ValueError):
            parse_latlng(34.05, -118.25)

    def test_rejects_non_numbers(self):
        with self.assertRaises(ValueError):
            parse_latlng("x", "y")


class UserLatLngHelperTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.user = User.objects.create_user("pin", "pin@example.com", "pw-12345!")

    def test_none_without_profile_or_pin(self):
        self.assertIsNone(user_latlng(self.user))
        UserProfile.objects.create(user=self.user)
        self.assertIsNone(user_latlng(self.user))

    def test_save_and_read_pin(self):
        save_user_latlng(self.user, 40.678, -73.944)
        self.assertEqual(user_latlng(self.user), (40.678, -73.944))
        profile = UserProfile.objects.get(user=self.user)
        self.assertIsNotNone(profile.location_updated_at)

    def test_clear_pin(self):
        save_user_latlng(self.user, 40.678, -73.944)
        clear_user_latlng(self.user)
        self.assertIsNone(user_latlng(self.user))


class SaveLocationViewTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        for place_id, name, cuisine, _day in [
            ("1", "GREEN LEAF", "Salads", "2024-07-04"),
            ("2", "LEAF AND CO", "Salads", "2024-07-03"),
            ("3", "TAQUERIA", "Mexican", "2024-07-02"),
            ("4", "THAI SPOT", "Thai", "2024-07-01"),
        ]:
            make_restaurant(
                place_id,
                name,
                boro="Brooklyn",
                street="1 Main St",
                zipcode="11201",
                cuisine=cuisine,
            )
        self.user = User.objects.create_user("loc", "loc@example.com", "pw-12345!")

    def test_requires_login(self):
        response = self.client.post(
            reverse("search:save_location"), {"lat": "40.7", "lng": "-74.0"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_saves_in_bounds_pin(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("search:save_location"), {"lat": "40.7128", "lng": "-74.0060"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertAlmostEqual(data["lat"], 40.7128)
        profile = UserProfile.objects.get(user=self.user)
        self.assertAlmostEqual(profile.location_lat, 40.7128)
        self.assertAlmostEqual(profile.location_lng, -74.0060)

    def test_rejects_out_of_bounds(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("search:save_location"), {"lat": "34.05", "lng": "-118.25"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

    def test_clear(self):
        self.client.force_login(self.user)
        save_user_latlng(self.user, 40.7, -74.0)
        response = self.client.post(reverse("search:save_location"), {"clear": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cleared"])
        self.assertIsNone(user_latlng(self.user))

    def test_home_hides_minimap_for_now(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("search:home"))
        self.assertNotContains(page, "location-minimap")
        self.assertNotContains(page, "location-pin-config")
