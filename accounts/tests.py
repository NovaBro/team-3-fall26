import io
import re
import tempfile
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import MoodLog, UserProfile
from accounts.tokens import email_verification_token

VALID_PASSWORD = "sTr0ngPass!2026x"


def _verify_url_from_outbox():
    body = mail.outbox[-1].body
    match = re.search(r"http://\S+/verify/\S+/", body)
    return match.group(0)


def _png_upload(name="me.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class SignupTests(TestCase):
    def test_signup_creates_inactive_user_and_profile_and_emails_a_link(self):
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
        self.assertRedirects(response, reverse("accounts:login"))
        user = User.objects.get(username="foodie")
        self.assertEqual(user.email, "foodie@example.com")
        self.assertFalse(user.is_active)
        self.assertTrue(user.profile)
        self.assertEqual(user.profile.name, "Sam Rivera")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["foodie@example.com"])
        self.assertIn("/verify/", mail.outbox[0].body)

    def test_signup_does_not_leak_the_verification_link_in_the_response(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "foodie",
                "name": "Sam Rivera",
                "email": "foodie@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
            follow=True,
        )
        self.assertNotContains(response, "/verify/")

    def test_cannot_log_in_before_verifying_email(self):
        self.client.post(
            reverse("accounts:signup"),
            {
                "username": "foodie",
                "name": "Sam Rivera",
                "email": "foodie@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "foodie", "password": VALID_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please confirm your email before logging in")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verify_link_activates_account_and_logs_in(self):
        self.client.post(
            reverse("accounts:signup"),
            {
                "username": "foodie",
                "name": "Sam Rivera",
                "email": "foodie@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )
        verify_url = _verify_url_from_outbox()

        response = self.client.get(verify_url)

        self.assertRedirects(response, reverse("accounts:profile"))
        user = User.objects.get(username="foodie")
        self.assertTrue(user.is_active)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_reusing_a_verify_link_does_not_grant_a_fresh_session(self):
        self.client.post(
            reverse("accounts:signup"),
            {
                "username": "foodie",
                "name": "Sam Rivera",
                "email": "foodie@example.com",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            },
        )
        verify_url = _verify_url_from_outbox()
        self.client.get(verify_url)
        self.client.logout()

        response = self.client.get(verify_url)

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_verify_link_cannot_be_reused_as_a_password_reset_token(self):
        user = User.objects.create_user(
            "foodie", "foodie@example.com", VALID_PASSWORD, is_active=False
        )
        token = email_verification_token.make_token(user)

        from django.contrib.auth.tokens import default_token_generator

        self.assertFalse(default_token_generator.check_token(user, token))

    def test_invalid_verify_token_shows_generic_error_and_stays_logged_out(self):
        user = User.objects.create_user(
            "foodie", "foodie@example.com", VALID_PASSWORD, is_active=False
        )
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        response = self.client.get(
            reverse("accounts:verify_email", args=[uid, "bad-token"])
        )

        self.assertRedirects(response, reverse("accounts:login"))
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertNotIn("_auth_user_id", self.client.session)

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
    # Logging out redirects to Find food, which reads stored map locations.
    databases = {"default", "community"}

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
                "phone_number": "(212) 555-0100",
                "promo_opt_in": "on",
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
        self.assertEqual(profile.phone_number, "(212) 555-0100")
        self.assertTrue(profile.promo_opt_in)

    def test_promo_opt_in_defaults_off_and_is_not_required(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {"action": "save_fixed", "name": "Sam Rivera"},
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        profile = UserProfile.objects.get(user=self.user)
        self.assertFalse(profile.promo_opt_in)
        self.assertEqual(profile.phone_number, "")

    def test_invalid_phone_number_shows_friendly_error(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {"action": "save_fixed", "name": "Sam Rivera", "phone_number": "abc"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter a valid phone number.")
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.phone_number, "")

    def test_other_users_cannot_see_phone_number_on_public_profile(self):
        self.client.post(
            reverse("accounts:profile"),
            {
                "action": "save_fixed",
                "name": "Sam Rivera",
                "phone_number": "(212) 555-0100",
            },
        )
        self.client.logout()

        response = self.client.get(
            reverse("accounts:view_profile", args=[self.user.username])
        )

        self.assertNotContains(response, "555-0100")

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


class SendPromoEmailCommandTests(TestCase):
    def test_sends_only_to_opted_in_users(self):
        opted_in = User.objects.create_user("ann", "ann@example.com", VALID_PASSWORD)
        UserProfile.objects.create(user=opted_in, promo_opt_in=True)
        opted_out = User.objects.create_user("bob", "bob@example.com", VALID_PASSWORD)
        UserProfile.objects.create(user=opted_out, promo_opt_in=False)

        call_command("send_promo_email", subject="Hi", message="New specials!")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ann@example.com"])

    def test_each_recipient_gets_their_own_message(self):
        for username in ("ann", "bob"):
            user = User.objects.create_user(
                username, f"{username}@example.com", VALID_PASSWORD
            )
            UserProfile.objects.create(user=user, promo_opt_in=True)

        call_command("send_promo_email", subject="Hi", message="New specials!")

        self.assertEqual(len(mail.outbox), 2)
        all_recipients = [r for m in mail.outbox for r in m.to]
        self.assertEqual(sorted(all_recipients), ["ann@example.com", "bob@example.com"])
        for message in mail.outbox:
            self.assertEqual(len(message.to), 1)

    def test_raises_when_nobody_opted_in(self):
        user = User.objects.create_user("ann", "ann@example.com", VALID_PASSWORD)
        UserProfile.objects.create(user=user, promo_opt_in=False)

        with self.assertRaises(CommandError):
            call_command("send_promo_email", subject="Hi", message="New specials!")
        self.assertEqual(len(mail.outbox), 0)
