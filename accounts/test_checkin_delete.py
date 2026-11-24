from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import MoodLog
from nycfood.test_utils import ALL_DATABASES

PASSWORD = "sTr0ngPass!2026x"


class PastCheckInTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.user = User.objects.create_user(username="foodie", password=PASSWORD)
        self.client.force_login(self.user)
        # One check-in per day: make the old one first, move it back, then today.
        self.old = MoodLog.objects.create(user=self.user, mood=2, energy_level=2)
        back = timezone.now() - timedelta(days=3)
        MoodLog.objects.filter(pk=self.old.pk).update(
            created_at=back, log_date=timezone.localdate(back)
        )
        self.today = MoodLog.objects.create(user=self.user, mood=3, energy_level=3)

    def post(self, **data):
        return self.client.post(reverse("accounts:profile"), data)

    def test_past_shows_delete_today_shows_edit(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, 'class="checkin-edit-btn"', count=1)
        self.assertContains(response, 'class="checkin-del-btn"', count=1)

    def test_past_entry_cannot_be_edited(self):
        response = self.post(
            action="edit_mood", log_id=str(self.old.pk), mood="5", energy_level="5"
        )
        self.assertEqual(response.status_code, 302)
        self.old.refresh_from_db()
        self.assertEqual(self.old.mood, 2)

    def test_delete_removes_own_entry(self):
        response = self.post(action="delete_mood", log_id=str(self.old.pk))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MoodLog.objects.filter(pk=self.old.pk).exists())
        self.assertTrue(MoodLog.objects.filter(pk=self.today.pk).exists())

    def test_cannot_delete_someone_elses_entry(self):
        other = User.objects.create_user(username="other", password=PASSWORD)
        theirs = MoodLog.objects.create(user=other, mood=1, energy_level=1)
        response = self.post(action="delete_mood", log_id=str(theirs.pk))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(MoodLog.objects.filter(pk=theirs.pk).exists())
