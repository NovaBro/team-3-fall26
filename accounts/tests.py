import io
import tempfile
from datetime import datetime, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import MoodLog, UserProfile
from accounts.mood import latest_check_in_for, today_ny, upsert_today_mood
from accounts.tokens import email_verification_token
from community.models import CommunitySubject, UserComment, UserRating
from nycfood.test_utils import ALL_DATABASES

VALID_PASSWORD = "sTr0ngPass!2026x"


def _png_upload(name="me.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class SignupTests(TestCase):
    databases = ALL_DATABASES

    def test_signup_creates_active_user_and_profile(self):
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
        self.assertTrue(user.is_active)
        self.assertTrue(user.profile)
        self.assertEqual(user.profile.name, "Sam Rivera")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 0)

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

    def test_can_log_in_immediately_after_signup(self):
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
        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertIn("_auth_user_id", self.client.session)

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
    databases = ALL_DATABASES

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
    databases = ALL_DATABASES

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
        self.assertContains(response, "name not set")
        self.assertContains(response, "No email yet")
        self.assertContains(response, "Personal details")
        self.assertContains(response, "Food preferences")
        # The photo control sits in Account details but saves with the form.
        self.assertContains(response, 'form="profile-form"')
        self.assertContains(response, "Check-in log")  # step175

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
                "favorite_foods": "Pizza, Dumplings",
                "disliked_foods": "Seafood",
                "health_goals": ["heart-health", "balanced-diet"],
                "allergies": ["nuts"],
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
        self.assertEqual(profile.allergies, "Nuts")
        self.assertEqual(profile.favorite_foods, "Pizza, Dumplings")
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

    def test_log_mood_creates_todays_entry(self):
        response = self.client.post(
            reverse("accounts:profile"),
            {"action": "log_mood", "mood": "4", "energy_level": "2"},
        )
        self.assertRedirects(response, reverse("accounts:profile"))
        log = MoodLog.objects.get(user=self.user)
        self.assertEqual(log.mood, 4)
        self.assertEqual(log.energy_level, 2)
        self.assertIsNotNone(log.created_at)
        self.assertIsNotNone(log.log_date)

    def test_log_mood_upserts_same_day(self):
        self.client.post(
            reverse("accounts:profile"),
            {"action": "log_mood", "mood": "2", "energy_level": "1"},
        )
        self.client.post(
            reverse("accounts:profile"),
            {"action": "log_mood", "mood": "5", "energy_level": "4"},
        )
        logs = MoodLog.objects.filter(user=self.user)
        self.assertEqual(logs.count(), 1)
        log = logs.get()
        self.assertEqual(log.mood, 5)
        self.assertEqual(log.energy_level, 4)

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

    def test_check_in_has_icon_scales_and_no_blank_choice(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertNotContains(response, 'name="mood" value=""')
        self.assertContains(response, 'class="checkin-scale"', count=2)
        self.assertContains(response, 'class="checkin-option__icon"', count=10)

    def test_mood_history_lists_recent_days_first(self):
        today = today_ny()
        MoodLog.objects.create(
            user=self.user, mood=1, energy_level=3, log_date=today - timedelta(days=2)
        )
        MoodLog.objects.create(
            user=self.user, mood=3, energy_level=3, log_date=today - timedelta(days=1)
        )
        MoodLog.objects.create(user=self.user, mood=5, energy_level=3, log_date=today)
        response = self.client.get(reverse("accounts:profile"))
        history = list(response.context["mood_history"])
        self.assertEqual([log.mood for log in history], [5, 3, 1])

    def test_logout_posts_and_redirects_home(self):
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("search:index"))
        self.assertNotIn("_auth_user_id", self.client.session)


class MoodHelperTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.user = User.objects.create_user("mooder", "m@example.com", VALID_PASSWORD)

    def test_upsert_keys_off_ny_calendar_day(self):
        # 1am UTC on Nov 15 is still Nov 14 in America/New_York (EDT/EST).
        late_ny_evening = datetime(2026, 11, 15, 1, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(today_ny(late_ny_evening).isoformat(), "2026-11-14")
        first = upsert_today_mood(self.user, 2, 2, when=late_ny_evening)
        second = upsert_today_mood(self.user, 5, 5, when=late_ny_evening)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(MoodLog.objects.filter(user=self.user).count(), 1)
        self.assertEqual(second.log_date.isoformat(), "2026-11-14")
        self.assertEqual(second.mood, 5)

    def test_latest_check_in_prefers_today_over_stale(self):
        today = today_ny()
        MoodLog.objects.create(
            user=self.user,
            mood=1,
            energy_level=1,
            log_date=today - timedelta(days=3),
        )
        today_log = upsert_today_mood(self.user, 4, 3)
        self.assertEqual(latest_check_in_for(self.user).pk, today_log.pk)


class ViewProfileTests(TestCase):
    databases = ALL_DATABASES

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


class AdminUserManagementTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.user = User.objects.create_user(
            "target", "target@example.com", VALID_PASSWORD, is_active=True
        )
        self.list_url = reverse("admin:auth_user_changelist")
        self.detail_url = reverse("admin:auth_user_change", args=[self.user.pk])

    def test_anonymous_and_non_staff_users_cannot_view_user_management(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 302)

        regular_user = User.objects.create_user(
            "regular", "regular@example.com", VALID_PASSWORD
        )
        self.client.force_login(regular_user)
        response = self.client.get(self.list_url)
        self.assertNotEqual(response.status_code, 200)
        self.assertNotContains(
            response, "target@example.com", status_code=response.status_code
        )

    def test_staff_with_view_permission_can_search_and_view_read_only_details(self):
        staff_user = User.objects.create_user(
            "manager", "manager@example.com", VALID_PASSWORD, is_staff=True
        )
        view_user_permission = Permission.objects.get(
            content_type__app_label="auth", codename="view_user"
        )
        staff_user.user_permissions.add(view_user_permission)
        self.client.force_login(staff_user)

        response = self.client.get(self.list_url, {"q": "target@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "target@example.com")

        UserProfile.objects.create(user=self.user, allergies="peanuts")
        MoodLog.objects.create(user=self.user, mood=5, energy_level=4)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "target@example.com")
        self.assertContains(response, "Mood check-ins")
        self.assertContains(response, ">1<")
        self.assertNotContains(response, "peanuts")
        self.assertNotContains(response, self.user.password)

        response = self.client.post(self.detail_url, {"is_active": "0"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(response.status_code, 403)

    def test_staff_with_view_permission_cannot_add_or_delete_users(self):
        staff_user = User.objects.create_user(
            "manager", "manager@example.com", VALID_PASSWORD, is_staff=True
        )
        view_user_permission = Permission.objects.get(
            content_type__app_label="auth", codename="view_user"
        )
        staff_user.user_permissions.add(view_user_permission)
        self.client.force_login(staff_user)

        add_url = reverse("admin:auth_user_add")
        delete_url = reverse("admin:auth_user_delete", args=[self.user.pk])
        self.assertEqual(self.client.get(add_url).status_code, 403)
        self.assertEqual(self.client.get(delete_url).status_code, 403)


class SuperuserDashboardTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "siteadmin", "admin@example.com", VALID_PASSWORD
        )
        self.user = User.objects.create_user(
            "target",
            "target@example.com",
            VALID_PASSWORD,
            first_name="Taylor",
            last_name="Example",
        )
        self.subject = CommunitySubject.objects.create(
            kind="restaurant_dohmh", key="google:1", name="Test Restaurant"
        )
        self.comment = UserComment.objects.create(
            subject=self.subject, user_id=self.user.pk, text="Helpful review"
        )
        UserRating.objects.create(subject=self.subject, user_id=self.user.pk, score=4)

    def test_only_superusers_can_access_dashboard_and_account_detail(self):
        dashboard_url = reverse("accounts:admin_dashboard")
        detail_url = reverse("accounts:admin_user_detail", args=[self.user.pk])

        self.client.force_login(self.user)
        self.assertEqual(self.client.get(dashboard_url).status_code, 403)
        self.assertEqual(self.client.get(detail_url).status_code, 403)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(dashboard_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)

    def test_accounts_tab_searches_and_shows_basic_activity_counts(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("accounts:admin_dashboard"), {"tab": "users", "q": "target"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "target@example.com")
        self.assertContains(response, "Taylor Example")
        self.assertNotContains(response, "Helpful review")
        self.assertContains(response, "<td>1</td>", count=2, html=True)

    def test_comment_tab_and_user_detail_show_comments_without_health_profile(self):
        UserProfile.objects.create(user=self.user, allergies="peanuts")
        self.client.force_login(self.admin)

        comments_response = self.client.get(
            reverse("accounts:admin_dashboard"),
            {"tab": "comments", "q": "target"},
        )
        self.assertEqual(comments_response.status_code, 200)
        self.assertContains(comments_response, "target")
        self.assertContains(comments_response, "Test Restaurant")
        self.assertContains(comments_response, "Helpful review")

        detail_response = self.client.get(
            reverse("accounts:admin_user_detail", args=[self.user.pk])
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Helpful review")
        self.assertContains(detail_response, "Comments: 1")
        self.assertContains(detail_response, "Ratings: 1")
        self.assertNotContains(detail_response, "peanuts")


class AdminDeleteUserTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "siteadmin", "admin@example.com", VALID_PASSWORD
        )
        self.other_admin = User.objects.create_superuser(
            "otheradmin", "otheradmin@example.com", VALID_PASSWORD
        )
        self.user = User.objects.create_user(
            "target", "target@example.com", VALID_PASSWORD
        )

    def test_non_superuser_cannot_delete(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:admin_delete_user", args=[self.user.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_delete_own_account(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:admin_delete_user", args=[self.admin.pk]),
            follow=True,
        )
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.assertContains(response, "You cannot delete your own account.")

    def test_admin_cannot_delete_another_admin(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:admin_delete_user", args=[self.other_admin.pk]),
            follow=True,
        )
        self.assertTrue(User.objects.filter(pk=self.other_admin.pk).exists())
        self.assertContains(response, "Cannot delete another administrator account.")

    def test_admin_can_delete_regular_user(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:admin_delete_user", args=[self.user.pk]),
            follow=True,
        )
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertContains(response, "target", html=False)
        self.assertContains(response, "was deleted.")


class AdminDeleteCommentTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.admin = User.objects.create_superuser(
            "siteadmin", "admin@example.com", VALID_PASSWORD
        )
        self.user = User.objects.create_user(
            "target", "target@example.com", VALID_PASSWORD
        )
        self.subject = CommunitySubject.objects.create(
            kind="restaurant_dohmh", key="google:1", name="Test Restaurant"
        )
        self.comment = UserComment.objects.create(
            subject=self.subject, user_id=self.user.pk, text="Helpful review"
        )

    def test_non_superuser_cannot_delete_comment(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:admin_delete_comment", args=[self.comment.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(UserComment.objects.filter(pk=self.comment.pk).exists())

    def test_admin_can_delete_comment_and_is_redirected_to_dashboard_by_default(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:admin_delete_comment", args=[self.comment.pk]),
            follow=True,
        )
        self.assertFalse(UserComment.objects.filter(pk=self.comment.pk).exists())
        self.assertContains(response, "Comment was deleted.")
        self.assertRedirects(response, reverse("accounts:admin_dashboard"))

    def test_admin_delete_comment_honors_safe_next_url(self):
        self.client.force_login(self.admin)
        next_url = reverse("accounts:admin_user_detail", args=[self.user.pk])
        response = self.client.post(
            reverse("accounts:admin_delete_comment", args=[self.comment.pk]),
            {"next": next_url},
        )
        self.assertRedirects(response, next_url)

    def test_admin_delete_comment_ignores_unsafe_next_url(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:admin_delete_comment", args=[self.comment.pk]),
            {"next": "https://evil.example.com/"},
        )
        self.assertRedirects(response, reverse("accounts:admin_dashboard"))


class SendPromoEmailCommandTests(TestCase):
    databases = ALL_DATABASES

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
