"""User location pin for distance-aware ranking."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from search.models import RestaurantInspection
from search.user_location import (
    clear_user_latlng,
    parse_latlng,
    save_user_latlng,
    user_latlng,
)


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


@patch("search.views.find_restaurant_place", return_value=None)
class SaveLocationViewTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        for camis, dba, cuisine, day in [
            ("1", "GREEN LEAF", "Salads", "2024-07-04"),
            ("2", "LEAF AND CO", "Salads", "2024-07-03"),
            ("3", "TAQUERIA", "Mexican", "2024-07-02"),
            ("4", "THAI SPOT", "Thai", "2024-07-01"),
        ]:
            RestaurantInspection.objects.create(
                camis=camis,
                dba=dba,
                boro="Brooklyn",
                street="1 Main St",
                zipcode="11201",
                cuisine=cuisine,
                inspection_date=day,
                grade="A",
            )
        self.user = User.objects.create_user("loc", "loc@example.com", "pw-12345!")

    def test_requires_login(self, _find):
        response = self.client.post(
            reverse("search:save_location"), {"lat": "40.7", "lng": "-74.0"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_saves_in_bounds_pin(self, _find):
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

    def test_rejects_out_of_bounds(self, _find):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("search:save_location"), {"lat": "34.05", "lng": "-118.25"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

    def test_clear(self, _find):
        self.client.force_login(self.user)
        save_user_latlng(self.user, 40.7, -74.0)
        response = self.client.post(reverse("search:save_location"), {"clear": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cleared"])
        self.assertIsNone(user_latlng(self.user))

    def test_home_hides_minimap_for_now(self, _find):
        self.client.force_login(self.user)
        page = self.client.get(reverse("search:home"))
        self.assertNotContains(page, "location-minimap")
        self.assertNotContains(page, "location-pin-config")
