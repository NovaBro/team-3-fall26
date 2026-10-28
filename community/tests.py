import io
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from community.keys import dohmh_key, farmers_market_key, google_key, grocery_key
from community.models import PlaceEnrichment, PlaceReview, UserComment, UserPhoto, UserRating


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, "PNG")
    return SimpleUploadedFile("meal.png", buffer.getvalue(), content_type="image/png")


class PinKeyTests(SimpleTestCase):
    def test_dohmh_key(self):
        self.assertEqual(dohmh_key("41155161"), "camis:41155161")

    def test_google_key(self):
        self.assertEqual(google_key("ChIJtest"), "google:ChIJtest")

    def test_grocery_key(self):
        self.assertEqual(
            grocery_key("Healthy Corner", "100 Main St", "11201"),
            "Healthy Corner|100 Main St|11201",
        )

    def test_farmers_market_key(self):
        self.assertEqual(
            farmers_market_key(2026, "Union Square Greenmarket", "E 17th St"),
            "2026|Union Square Greenmarket|E 17th St",
        )


class CommunityPanelTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        self.user = User.objects.create_user(username="foodie", password="sTr0ngPass!2026x")
        self.kind = "restaurant_dohmh"
        self.key = dohmh_key("1")
        place = PlaceEnrichment.objects.create(
            camis="1",
            display_name="Joe's Pizza",
            rating=4.5,
            user_rating_count=10,
        )
        PlaceReview.objects.create(
            place=place, author_name="Sam", rating=5, text="Best slice.", relative_time="a week ago"
        )

    def _detail(self):
        return reverse("community:detail", kwargs={"kind": self.kind, "key": self.key})

    def test_public_payload_includes_google_reviews(self):
        response = self.client.get(self._detail(), {"name": "Joe's Pizza", "address": "1 Main St"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["authenticated"])
        self.assertEqual(payload["google"]["rating"], 4.5)
        self.assertEqual(payload["google"]["reviews"][0]["text"], "Best slice.")
        self.assertEqual(payload["comments"], [])
        self.assertIsNone(payload["average_rating"])

    def test_post_requires_login(self):
        response = self.client.post(
            reverse("community:rate", kwargs={"kind": self.kind, "key": self.key}),
            {"rating": "5"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_rating_is_replaced_for_the_same_user(self):
        self.client.force_login(self.user)
        rate = reverse("community:rate", kwargs={"kind": self.kind, "key": self.key})
        first = self.client.post(rate, {"rating": "4", "name": "Joe's Pizza"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["user_rating"], 4)
        second = self.client.post(rate, {"rating": "2"})
        self.assertEqual(second.json()["user_rating"], 2)
        self.assertEqual(second.json()["average_rating"], 2.0)
        self.assertEqual(UserRating.objects.count(), 1)
        rejected = self.client.post(rate, {"rating": "9"})
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(UserRating.objects.get().score, 2)

    def test_comment_is_saved(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("community:comment", kwargs={"kind": self.kind, "key": self.key}),
            {"text": "  Crowded but worth it.  "},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["comments"][0]["text"], "Crowded but worth it.")
        self.assertEqual(response.json()["comments"][0]["author"], "foodie")
        self.assertEqual(UserComment.objects.count(), 1)

        empty = self.client.post(
            reverse("community:comment", kwargs={"kind": self.kind, "key": self.key}),
            {"text": "   "},
        )
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(UserComment.objects.count(), 1)

    def test_photo_upload_and_rejection(self):
        self.client.force_login(self.user)
        url = reverse("community:photo", kwargs={"kind": self.kind, "key": self.key})
        rejected = self.client.post(
            url, {"photo": SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")}
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(UserPhoto.objects.count(), 0)

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            saved = self.client.post(url, {"photo": _png()})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(len(saved.json()["photos"]), 1)
        self.assertTrue(saved.json()["photos"][0]["url"])
        self.assertEqual(UserPhoto.objects.count(), 1)

    def test_unknown_kind_is_not_found(self):
        response = self.client.get(
            reverse("community:detail", kwargs={"kind": "not-a-pin", "key": "x"})
        )
        self.assertEqual(response.status_code, 404)
