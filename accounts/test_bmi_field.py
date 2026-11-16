"""The profile form shows BMI, worked out from weight and height, read-only.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test accounts.test_bmi_field
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.forms import UserProfileForm
from accounts.models import UserProfile


class BmiFieldTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        self.user = User.objects.create_user("bmi", password="pw-12345!")
        self.client.force_login(self.user)

    def test_shows_bmi_from_saved_weight_and_height(self):
        UserProfile.objects.create(user=self.user, weight_lbs=200, height_in=69)
        html = self.client.get(reverse("accounts:profile")).content.decode()
        self.assertIn('id="id_bmi"', html)
        self.assertIn('value="29.5"', html)
        self.assertIn("disabled", html.split('id="id_bmi"')[0].rsplit("<input", 1)[1])

    def test_empty_without_weight_or_height(self):
        form = UserProfileForm(instance=UserProfile(user=self.user, weight_lbs=150))
        self.assertEqual(form.fields["bmi"].initial, "")

    def test_typed_bmi_is_ignored(self):
        profile = UserProfile.objects.create(user=self.user)
        form = UserProfileForm(
            data={"weight_lbs": "150", "height_in": "69", "bmi": "99"},
            instance=profile,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotEqual(form.cleaned_data.get("bmi"), "99")
        self.assertNotIn("bmi", [f.name for f in UserProfile._meta.fields])
