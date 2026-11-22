"""The profile page lists the user's own liked places (only for them).

GOOGLE_MAPS_JS_KEY=dummy python manage.py test accounts.test_liked_places
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from community.models import RecommendationFeedback
from nycfood.test_utils import ALL_DATABASES


class LikedPlacesTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.ann = User.objects.create_user("ann", password="pw-12345!")
        self.bob = User.objects.create_user("bob", password="pw-12345!")
        RecommendationFeedback.objects.create(
            user_id=self.ann.pk,
            place_id="10",
            name="GREEN LEAF",
            cuisine="Salads",
            value=RecommendationFeedback.LIKE,
        )
        RecommendationFeedback.objects.create(
            user_id=self.ann.pk,
            place_id="11",
            name="SKIPPED DINER",
            cuisine="American",
            value=RecommendationFeedback.NOT_INTERESTED,
        )
        self.url = reverse("accounts:view_profile", args=["ann"])

    def test_owner_sees_liked_places_only(self):
        self.client.force_login(self.ann)
        html = self.client.get(self.url).content.decode()
        self.assertIn("Liked places", html)
        self.assertIn("Green Leaf", html)
        self.assertIn('href="/restaurant/10/"', html)
        start, end = html.index("Liked places"), html.index("Not interested")
        liked = html[start:end]
        self.assertNotIn("Skipped Diner", liked)  # listed under Not interested

    def test_other_people_do_not_see_the_list(self):
        self.client.force_login(self.bob)
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("Liked places", html)
        self.client.logout()
        self.assertNotIn("Liked places", self.client.get(self.url).content.decode())

    def test_empty_list_message(self):
        self.client.force_login(self.bob)
        url = reverse("accounts:view_profile", args=["bob"])
        self.assertIn("No liked places yet", self.client.get(url).content.decode())


class DeleteLikedPlacesTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.ann = User.objects.create_user("ann", password="pw-12345!")
        self.bob = User.objects.create_user("bob", password="pw-12345!")
        for camis in ("1", "2", "3"):
            RecommendationFeedback.objects.create(
                user_id=self.ann.pk, place_id=camis, name=f"PLACE {camis}", value=1
            )
        RecommendationFeedback.objects.create(
            user_id=self.ann.pk, place_id="9", name="HIDDEN", value=-1
        )
        RecommendationFeedback.objects.create(
            user_id=self.bob.pk, place_id="1", name="PLACE 1", value=1
        )
        self.url = reverse("accounts:delete_liked_places")

    def likes(self, user):
        return set(
            RecommendationFeedback.objects.filter(user_id=user.pk, value=1).values_list(
                "place_id", flat=True
            )
        )

    def test_delete_selected(self):
        self.client.force_login(self.ann)
        page = self.client.post(
            self.url, {"action": "delete_selected", "place_id": ["1", "3"]}
        )
        self.assertRedirects(page, reverse("accounts:view_profile", args=["ann"]))
        self.assertEqual(self.likes(self.ann), {"2"})
        self.assertEqual(self.likes(self.bob), {"1"})  # other users untouched

    def test_delete_all_keeps_not_interested(self):
        self.client.force_login(self.ann)
        self.client.post(self.url, {"action": "delete_all"})
        self.assertEqual(self.likes(self.ann), set())
        self.assertTrue(
            RecommendationFeedback.objects.filter(
                user_id=self.ann.pk, value=-1
            ).exists()
        )

    def test_nothing_selected(self):
        self.client.force_login(self.ann)
        page = self.client.post(self.url, {"action": "delete_selected"}, follow=True)
        self.assertContains(page, "No places were selected.")
        self.assertEqual(self.likes(self.ann), {"1", "2", "3"})

    def test_login_and_post_required(self):
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.client.force_login(self.ann)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_profile_has_checkboxes_and_buttons(self):
        self.client.force_login(self.ann)
        html = self.client.get(
            reverse("accounts:view_profile", args=["ann"])
        ).content.decode()
        start, end = html.index("Liked places"), html.index("<h2>Not interested")
        liked = html[start:end]
        self.assertEqual(liked.count('type="checkbox" name="place_id"'), 3)
        self.assertIn("Delete selected", html)
        self.assertIn("Delete all", html)


class HiddenPlacesTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.ann = User.objects.create_user("ann", password="pw-12345!")
        for camis in ("5", "6"):
            RecommendationFeedback.objects.create(
                user_id=self.ann.pk, place_id=camis, name=f"SKIP {camis}", value=-1
            )
        RecommendationFeedback.objects.create(
            user_id=self.ann.pk, place_id="7", name="LOVED", value=1
        )
        self.client.force_login(self.ann)
        self.url = reverse("accounts:restore_hidden_places")

    def hidden(self):
        return set(
            RecommendationFeedback.objects.filter(
                user_id=self.ann.pk, value=-1
            ).values_list("place_id", flat=True)
        )

    def test_profile_lists_hidden_places_below_likes(self):
        html = self.client.get(
            reverse("accounts:view_profile", args=["ann"])
        ).content.decode()
        self.assertLess(html.index("Liked places"), html.index("Not interested"))
        self.assertIn("Skip 5", html)
        self.assertIn("Show all again", html)
        self.assertIn("btn--danger", html)

    def test_show_selected_again(self):
        self.client.post(self.url, {"action": "show_selected", "place_id": ["5"]})
        self.assertEqual(self.hidden(), {"6"})

    def test_show_all_again_keeps_likes(self):
        self.client.post(self.url, {"action": "show_all"})
        self.assertEqual(self.hidden(), set())
        self.assertTrue(RecommendationFeedback.objects.filter(place_id="7").exists())
