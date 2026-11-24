from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import MoodLog
from nycfood.test_utils import ALL_DATABASES

PASSWORD = "sTr0ngPass!2026x"


class LoginReturnsToPreviousPageTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        User.objects.create_user(username="foodie", password=PASSWORD)

    def login(self):
        return self.client.post(
            reverse("accounts:login"), {"username": "foodie", "password": PASSWORD}
        )

    def test_goes_back_to_the_page_before_login(self):
        self.client.get(
            reverse("accounts:login"), HTTP_REFERER="http://testserver/search/?q=kale"
        )
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/search/?q=kale")

    def test_ignores_login_page_and_other_hosts(self):
        self.client.get(
            reverse("accounts:login"), HTTP_REFERER="http://testserver/login/"
        )
        self.client.get(
            reverse("accounts:login"), HTTP_REFERER="https://evil.example/search/"
        )
        response = self.login()
        self.assertRedirects(
            response, reverse("accounts:profile"), fetch_redirect_response=False
        )

    def test_next_still_wins(self):
        self.client.get(
            reverse("accounts:login"), HTTP_REFERER="http://testserver/search/"
        )
        response = self.client.post(
            reverse("accounts:login") + "?next=/",
            {"username": "foodie", "password": PASSWORD, "next": "/"},
        )
        self.assertEqual(response.url, "/")


class CheckInLogEditTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.user = User.objects.create_user(username="foodie", password=PASSWORD)
        self.client.force_login(self.user)
        self.log = MoodLog.objects.create(user=self.user, mood=2, energy_level=2)

    def edit(self, **data):
        payload = {"action": "edit_mood", "log_id": str(self.log.pk)}
        payload.update(data)
        return self.client.post(reverse("accounts:profile"), payload)

    def test_edit_changes_the_entry(self):
        response = self.edit(mood="5", energy_level="4")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("#checkin-log"))
        self.log.refresh_from_db()
        self.assertEqual((self.log.mood, self.log.energy_level), (5, 4))
        self.assertEqual(MoodLog.objects.count(), 1)

    def test_invalid_value_shows_error_and_keeps_entry(self):
        response = self.edit(mood="9", energy_level="4")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pick a mood from the list.")
        self.log.refresh_from_db()
        self.assertEqual(self.log.mood, 2)

    def test_cannot_edit_someone_elses_entry(self):
        other = User.objects.create_user(username="other", password=PASSWORD)
        theirs = MoodLog.objects.create(user=other, mood=1, energy_level=1)
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "action": "edit_mood",
                "log_id": str(theirs.pk),
                "mood": "5",
                "energy_level": "5",
            },
        )
        self.assertEqual(response.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.mood, 1)

    def test_profile_shows_edit_buttons(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "Check-in log")
        self.assertContains(response, 'class="checkin-edit-btn"')
