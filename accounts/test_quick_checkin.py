"""Home page mood / energy check-in (accounts/checkin.py, quick_checkin)."""

from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts import checkin
from accounts.models import MoodLog
from search.models import RestaurantInspection


class HeadlineTests(TestCase):
    def test_default_without_check_in(self):
        self.assertEqual(checkin.headline(), checkin.DEFAULT_HEADLINE)

    def test_levels(self):
        self.assertEqual(checkin.headline(5, 5)[0], "Ready for something great?")
        self.assertEqual(checkin.headline(1, 2)[0], "Take it easy today")
        self.assertEqual(checkin.headline(3, 3)[0], "Just a solid meal today")

    def test_one_side_counts_the_other_as_middle(self):
        self.assertEqual(checkin.headline(4, None), checkin.headline(4, 3))
        self.assertEqual(checkin.headline(None, 1), checkin.headline(3, 1))


class QuickCheckinTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("mia", password="pw-12345!")
        self.client.force_login(self.user)
        self.url = reverse("accounts:quick_checkin")

    def post(self, kind, value, json=True):
        headers = {"HTTP_ACCEPT": "application/json"} if json else {}
        return self.client.post(self.url, {"kind": kind, "value": value}, **headers)

    def test_mood_then_energy_share_todays_row(self):
        response = self.post("mood", 5)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["label"], "Great")
        self.post("energy", 1)
        log = MoodLog.objects.get(user=self.user)
        self.assertEqual((log.mood, log.energy_level), (5, 1))
        self.assertEqual(response.json()["title"], checkin.headline(5, None)[0])

    def test_changing_mood_updates_the_same_row(self):
        self.post("mood", 2)
        response = self.post("mood", 4)
        self.assertEqual(MoodLog.objects.count(), 1)
        self.assertEqual(MoodLog.objects.get().mood, 4)
        self.assertIn("<svg", response.json()["icon"])

    def test_yesterdays_check_in_is_left_alone(self):
        old = MoodLog.objects.create(user=self.user, mood=1, energy_level=1)
        MoodLog.objects.filter(pk=old.pk).update(
            log_date=(checkin.start_of_today() - timedelta(days=1)).date(),
            created_at=checkin.start_of_today() - timedelta(hours=1),
        )
        self.post("mood", 5)
        self.assertEqual(MoodLog.objects.count(), 2)
        self.assertEqual(MoodLog.objects.get(pk=old.pk).mood, 1)

    def test_bad_input(self):
        self.assertEqual(self.post("mood", 9).status_code, 400)
        self.assertEqual(self.post("hunger", 3).status_code, 400)
        self.assertEqual(self.post("mood", "x").status_code, 400)
        self.assertRedirects(
            self.post("mood", 9, json=False),
            reverse("search:home"),
            fetch_redirect_response=False,
        )
        self.assertFalse(MoodLog.objects.exists())

    def test_plain_form_post_goes_back(self):
        response = self.client.post(
            self.url, {"kind": "energy", "value": 4, "next": "/?boro=Bronx"}
        )
        self.assertRedirects(response, "/?boro=Bronx", fetch_redirect_response=False)
        response = self.client.post(
            self.url, {"kind": "energy", "value": 4, "next": "https://evil.example/"}
        )
        self.assertRedirects(
            response, reverse("search:home"), fetch_redirect_response=False
        )

    def test_login_and_post_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        response = self.client.post(self.url, {"kind": "mood", "value": 3})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])


class TodayTests(TestCase):
    def test_start_of_today_is_new_york_midnight(self):
        now = datetime(2026, 11, 17, 3, 30, tzinfo=checkin.NEW_YORK)
        start = checkin.start_of_today(now)
        self.assertEqual((start.hour, start.day), (0, 17))
        self.assertEqual(start.tzinfo, checkin.NEW_YORK)

    def test_history_labels_handle_empty_fields(self):
        user = User.objects.create_user("lee", password="pw-12345!")
        log = MoodLog.objects.create(user=user, mood=4)
        self.assertEqual(log.mood_display_label, "Good")
        self.assertEqual(log.energy_display_label, "—")
        self.assertEqual(log.energy_icon, "")


class HomePageTests(TestCase):
    databases = {"default", "community"}

    def test_logged_out_sees_default_banner_and_no_picker(self):
        response = self.client.get(reverse("search:home"))
        self.assertContains(response, checkin.DEFAULT_HEADLINE[0])
        self.assertNotContains(response, "mood-pick__btn")

    def test_logged_in_sees_picker_and_todays_headline(self):
        RestaurantInspection.objects.create(
            camis="70001",
            dba="GREEN BOWL",
            boro="Queens",
            street="1 Main St",
            zipcode="11101",
            cuisine="Salads",
            inspection_date="2026-06-01",
            grade="A",
        )
        user = User.objects.create_user("ana", password="pw-12345!")
        MoodLog.objects.create(user=user, mood=1, energy_level=1)
        self.client.force_login(user)
        response = self.client.get(reverse("search:home"))
        self.assertContains(response, "mood-pick__btn")
        self.assertContains(response, "Take it easy today")
