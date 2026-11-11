import io
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from community.keys import (
    DOHMH,
    FARMERS_MARKET,
    GROCERY,
    dohmh_key,
    farmers_market_key,
    google_key,
    grocery_key,
)
from community.models import (
    PlaceEnrichment,
    PlaceReview,
    UserComment,
    UserPhoto,
    UserRating,
)


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
        self.user = User.objects.create_user(
            username="foodie", password="sTr0ngPass!2026x"
        )
        self.kind = "restaurant_dohmh"
        self.key = dohmh_key("1")
        place = PlaceEnrichment.objects.create(
            kind=DOHMH,
            key=self.key,
            camis="1",
            display_name="Joe's Pizza",
            rating=4.5,
            user_rating_count=10,
        )
        PlaceReview.objects.create(
            place=place,
            author_name="Sam",
            rating=5,
            text="Best slice.",
            relative_time="a week ago",
        )

    def _detail(self):
        return reverse("community:detail", kwargs={"kind": self.kind, "key": self.key})

    def test_public_payload_includes_google_reviews(self):
        response = self.client.get(
            self._detail(), {"name": "Joe's Pizza", "address": "1 Main St"}
        )
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
        comment = response.json()["comments"][0]
        self.assertEqual(comment["text"], "Crowded but worth it.")
        self.assertEqual(comment["author"], "foodie")
        self.assertEqual(comment["replies"], [])
        self.assertEqual(comment["photos"], [])
        self.assertEqual(response.json()["created_comment_id"], comment["id"])
        self.assertEqual(UserComment.objects.count(), 1)

        empty = self.client.post(
            reverse("community:comment", kwargs={"kind": self.kind, "key": self.key}),
            {"text": "   "},
        )
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(UserComment.objects.count(), 1)

    def test_reply_and_comment_photo(self):
        self.client.force_login(self.user)
        comment_url = reverse(
            "community:comment", kwargs={"kind": self.kind, "key": self.key}
        )
        photo_url = reverse(
            "community:photo", kwargs={"kind": self.kind, "key": self.key}
        )
        parent = self.client.post(comment_url, {"text": "Try the slices."})
        parent_id = parent.json()["created_comment_id"]

        reply = self.client.post(
            comment_url, {"text": "Agreed!", "parent_id": parent_id}
        )
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(len(reply.json()["comments"]), 1)
        self.assertEqual(reply.json()["comments"][0]["replies"][0]["text"], "Agreed!")
        self.assertEqual(UserComment.objects.count(), 2)

        nested = self.client.post(
            comment_url,
            {
                "text": "too deep",
                "parent_id": reply.json()["created_comment_id"],
            },
        )
        self.assertEqual(nested.status_code, 400)
        self.assertEqual(UserComment.objects.count(), 2)

        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            saved = self.client.post(
                photo_url, {"photo": _png(), "comment_id": parent_id}
            )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["photos"], [])
        self.assertEqual(len(saved.json()["comments"][0]["photos"]), 1)
        self.assertEqual(UserPhoto.objects.get().comment_id, parent_id)

    def test_comment_under_google_review(self):
        self.client.force_login(self.user)
        review = PlaceReview.objects.get(author_name="Sam")
        response = self.client.post(
            reverse("community:comment", kwargs={"kind": self.kind, "key": self.key}),
            {"text": "Same here!", "google_review_id": review.id},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["comments"], [])
        google_comments = payload["google"]["reviews"][0]["comments"]
        self.assertEqual(google_comments[0]["text"], "Same here!")
        self.assertEqual(UserComment.objects.get().google_review_id, review.id)

    def test_photo_upload_and_rejection(self):
        self.client.force_login(self.user)
        url = reverse("community:photo", kwargs={"kind": self.kind, "key": self.key})
        rejected = self.client.post(
            url,
            {
                "photo": SimpleUploadedFile(
                    "note.txt", b"hello", content_type="text/plain"
                )
            },
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(UserPhoto.objects.count(), 0)

        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            saved = self.client.post(url, {"photo": _png()})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(len(saved.json()["photos"]), 1)
        self.assertTrue(saved.json()["photos"][0]["url"])
        self.assertIsNone(UserPhoto.objects.get().comment_id)
        self.assertEqual(UserPhoto.objects.count(), 1)

    def test_unknown_kind_is_not_found(self):
        response = self.client.get(
            reverse("community:detail", kwargs={"kind": "not-a-pin", "key": "x"})
        )
        self.assertEqual(response.status_code, 404)

    def test_market_and_grocery_google_payload(self):
        market_key = farmers_market_key(2026, "Union Square", "E 17th St")
        grocery_key_value = grocery_key("Healthy Corner", "100 Main St", "11201")
        PlaceEnrichment.objects.create(
            kind=FARMERS_MARKET,
            key=market_key,
            display_name="Union Square Greenmarket",
            rating=4.2,
            user_rating_count=50,
        )
        store = PlaceEnrichment.objects.create(
            kind=GROCERY,
            key=grocery_key_value,
            display_name="Healthy Corner",
            rating=4.0,
            user_rating_count=12,
        )
        PlaceReview.objects.create(
            place=store,
            author_name="Alex",
            rating=4,
            text="Fresh produce.",
        )

        market = self.client.get(
            reverse(
                "community:detail",
                kwargs={"kind": FARMERS_MARKET, "key": market_key},
            ),
            {"name": "Union Square"},
        )
        self.assertEqual(market.status_code, 200)
        self.assertEqual(market.json()["google"]["rating"], 4.2)
        self.assertEqual(market.json()["google"]["reviews"], [])

        grocery = self.client.get(
            reverse(
                "community:detail",
                kwargs={"kind": GROCERY, "key": grocery_key_value},
            ),
            {"name": "Healthy Corner"},
        )
        self.assertEqual(grocery.status_code, 200)
        self.assertEqual(grocery.json()["google"]["reviews"][0]["text"], "Fresh produce.")
