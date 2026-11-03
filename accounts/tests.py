import io
import tempfile
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import MoodLog, UserProfile

VALID_PASSWORD = "sTr0ngPass!2026x"


def _png_upload(name="me.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class SignupTests(TestCase):
    def test_signup_creates_user_and_profile_and_logs_in(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "foodie",
                "name": "Sam Rivera",
                "email": "foodie@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        user = User.objects.get(username="foodie")
        self.assertEqual(user.email, "foodie@example.com")
        self.assertTrue(user.profile)
        self.assertEqual(user.profile.name, "Sam Rivera")
        self.assertEqual(user.email, "foodie@example.com")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_signup_requires_a_valid_email(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "foodie",
                "name": "Sam Rivera",
                "email": "not-an-email",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a valid email address.")
        self.assertFalse(User.objects.filter(username="foodie").exists())

    def test_signup_with_mismatched_passwords_shows_error(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "foodie",
                "name": "Sam Rivera",
                "email": "foodie@example.com",
                "password1": VALID_PASSWORD,
                "password2": "nope",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The two password fields")
        self.assertContains(response, "Unable to register")
        self.assertFalse(User.objects.filter(username="foodie").exists())

    def test_duplicate_email_rejected(self):
        User.objects.create_user("bob", "ANN@example.com", VALID_PASSWORD)
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "ann",
                "name": "Ann Lee",
                "email": "ann@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )
        self.assertContains(response, "already exists")
        self.assertContains(response, "An account with this email already exists.")
        self.assertFalse(User.objects.filter(username="ann").exists())


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="foodie", password=VALID_PASSWORD)

    def test_login_page_renders(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Log in")

    def test_login_redirects_to_profile(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "foodie", "password": VALID_PASSWORD},
        )
        self.assertRedirects(response, reverse("accounts:profile"))

    def test_wrong_password_shows_error(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "foodie", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a correct username and password.")


class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="foodie", password=VALID_PASSWORD)
        self.client.force_login(self.user)

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("accounts:profile"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:profile')}",
        )

    def test_profile_page_renders_both_sections(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Account details")
        self.assertContains(response, "foodie")
        self.assertContains(response, "Not provided yet")
        self.assertContains(response, "Fixed user inputs")
        self.assertContains(response, "Variable user inputs")

    def test_profile_page_shows_saved_name_and_contact_email(self):
        self.user.email = "sam@example.com"
        self.user.save(update_fields=["email"])
        UserProfile.objects.create(user=self.user, name="Sam Rivera")

        response = self.client.get(reverse("accounts:profile"))

        self.assertContains(response, "foodie")
        self.assertContains(response, "Sam Rivera")
        self.assertContains(response, "sam@example.com")

    def test_saving_fixed_inputs_persists_fields(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {
                "action": "save_fixed",
                "first_name": "Sam",
                "last_name": "Rivera",
                "name": "Sam Rivera",
                "email": "sam@example.com",
                "home_address": "123 Main St, Brooklyn, NY",
                "age": "28",
                "gender": "non-binary",
                "weight_lbs": "150.5",
                "height_in": "68",
                "favorite_foods": "pizza, dumplings",
                "disliked_foods": "mushrooms",
                "health_goals": ["heart-health", "balanced-diet"],
                "allergies": "peanuts",
            },
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        profile = UserProfile.objects.get(user=self.user)
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("Sam", "Rivera"))
        self.assertEqual(profile.name, "Sam Rivera")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "sam@example.com")
        self.assertEqual(profile.home_address, "123 Main St, Brooklyn, NY")
        self.assertEqual(profile.age, 28)
        self.assertEqual(profile.gender, "non-binary")
        self.assertEqual(profile.weight_lbs, 150.5)
        self.assertEqual(profile.height_in, 68)
        self.assertEqual(profile.health_goals, ["heart-health", "balanced-diet"])
        self.assertEqual(profile.allergies, "peanuts")

    def test_saving_profile_picture_uploads_image(self):
        image_bytes = BytesIO()
        Image.new("RGB", (1, 1), color="red").save(image_bytes, format="PNG")

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse("accounts:profile"),
                    {
                        "action": "save_fixed",
                        "name": "Sam Rivera",
                        "picture": SimpleUploadedFile(
                            "profile.png",
                            image_bytes.getvalue(),
                            content_type="image/png",
                        ),
                    },
                )

        self.assertRedirects(response, reverse("accounts:profile"))
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.name, "Sam Rivera")
        self.assertTrue(profile.picture.name.startswith("profile_pictures/"))

    def test_invalid_age_shows_friendly_error(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {"action": "save_fixed", "age": "999"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Age must be 120 or less.")
        profile = UserProfile.objects.get(user=self.user)
        self.assertIsNone(profile.age)

    def test_upload_picture(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            response = self.client.post(
                reverse("accounts:profile"),
                {"action": "save_fixed", "picture": _png_upload()},
            )
            self.assertRedirects(response, reverse("accounts:profile"))
            profile = UserProfile.objects.get(user=self.user)
            self.assertTrue(profile.picture.name.startswith("profile_pictures/"))

    def test_log_mood_appends_timestamped_entry(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {"action": "log_mood", "mood": "4", "energy_level": "2"},
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        log = MoodLog.objects.get(user=self.user)
        self.assertEqual(log.mood, 4)
        self.assertEqual(log.energy_level, 2)
        self.assertIsNotNone(log.created_at)

    def test_log_mood_does_not_alter_fixed_profile(self):
        self.client.post(
            reverse("accounts:profile"),
            {"action": "save_fixed", "name": "Sam Rivera"},
        )
        self.client.post(
            reverse("accounts:profile"),
            {"action": "log_mood", "mood": "3", "energy_level": "3"},
        )
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.name, "Sam Rivera")
        self.assertEqual(MoodLog.objects.filter(user=self.user).count(), 1)

    def test_invalid_mood_shows_friendly_error(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {"action": "log_mood", "mood": "9", "energy_level": "3"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pick a mood from the list.")
        self.assertFalse(MoodLog.objects.exists())

    def test_mood_history_lists_recent_entries_first(self):
        for mood in (1, 3, 5):
            self.client.post(
                reverse("accounts:profile"),
                {"action": "log_mood", "mood": str(mood), "energy_level": "3"},
            )
        response = self.client.get(reverse("accounts:profile"))
        history = list(response.context["mood_history"])
        self.assertEqual([log.mood for log in history], [5, 3, 1])

    def test_logout_posts_and_redirects_home(self):
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("search:index"))
        self.assertNotIn("_auth_user_id", self.client.session)


class ViewProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "ann",
            "ann@example.com",
            VALID_PASSWORD,
            first_name="Ann",
            last_name="Lee",
        )

    def test_public_profile_shows_name(self):
        response = self.client.get(reverse("accounts:view_profile", args=["ann"]))
        self.assertContains(response, "Ann Lee")

    def test_unknown_username_404s(self):
        response = self.client.get(reverse("accounts:view_profile", args=["nope"]))
        self.assertEqual(response.status_code, 404)
