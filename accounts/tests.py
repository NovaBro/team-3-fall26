from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class SignupTests(TestCase):
    data = {
        "username": "ann",
        "email": "ann@example.com",
        "password1": "S3cure-pass-9",
        "password2": "S3cure-pass-9",
    }

    def test_signup_creates_user_and_logs_in(self):
        response = self.client.post(reverse("accounts:signup"), self.data, follow=True)
        self.assertTrue(User.objects.filter(username="ann").exists())
        self.assertIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Account created successfully")

    def test_duplicate_email_rejected(self):
        User.objects.create_user("bob", "ANN@example.com", "x")
        response = self.client.post(reverse("accounts:signup"), self.data)
        self.assertContains(response, "already exists")
        self.assertContains(response, "An account with this email already exists.")
        self.assertFalse(User.objects.filter(username="ann").exists())

    def test_mismatched_passwords_rejected(self):
        bad = {**self.data, "password2": "different"}
        response = self.client.post(reverse("accounts:signup"), bad)
        self.assertContains(response, "didn")  # "didn't match"
        self.assertContains(response, "Unable to register")
        self.assertFalse(User.objects.filter(username="ann").exists())


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ann", "ann@example.com", "S3cure-pass-9")

    def test_login_page_renders(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.status_code, 200)

    def test_login_and_logout(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "ann", "password": "S3cure-pass-9"},
        )
        self.assertRedirects(response, reverse("search:index"))
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("search:index"))
        self.assertNotIn("_auth_user_id", self.client.session)


class EditProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ann", "ann@example.com", "S3cure-pass-9")
        self.url = reverse("accounts:edit_profile")

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_edit_name(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"first_name": "Ann", "last_name": "Lee"})
        self.assertRedirects(response, self.url)
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.last_name), ("Ann", "Lee"))

    def test_upload_picture(self):
        import io
        import tempfile

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (4, 4)).save(buf, "PNG")
        image = SimpleUploadedFile("me.png", buf.getvalue(), content_type="image/png")

        self.client.force_login(self.user)
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            self.client.post(self.url, {"first_name": "", "last_name": "", "picture": image})
            self.user.profile.refresh_from_db()
            self.assertTrue(self.user.profile.picture.name.startswith("profiles/"))


class ViewProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "ann", "ann@example.com", "S3cure-pass-9", first_name="Ann", last_name="Lee"
        )

    def test_public_profile_shows_name(self):
        response = self.client.get(reverse("accounts:view_profile", args=["ann"]))
        self.assertContains(response, "Ann Lee")

    def test_unknown_username_404s(self):
        response = self.client.get(reverse("accounts:view_profile", args=["nope"]))
        self.assertEqual(response.status_code, 404)
