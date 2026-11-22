"""The one-time CAMIS -> Google place id conversion (community/0011)."""

from django.apps import apps
from django.test import TestCase

from community.dohmh_conversion import DOHMH, convert
from community.keys import GOOGLE
from community.models import (
    CommunitySubject,
    HealthScore,
    LocationLookup,
    MenuEstimate,
    PlaceEnrichment,
    PlaceReview,
    RecommendationFeedback,
    Restaurant,
    UserComment,
    UserRating,
    shuffle_seed,
)
from nycfood.test_utils import ALL_DATABASES


class ConversionTests(TestCase):
    databases = ALL_DATABASES

    def enrichment(self, camis, place_id, **fields):
        return PlaceEnrichment.objects.create(
            kind=DOHMH,
            key=f"camis:{camis}",
            place_id=place_id,
            display_name=fields.pop("name", f"Place {camis}"),
            formatted_address="1 Main St, Brooklyn, NY 11201",
            rating=4.4,
            **fields,
        )

    def run_conversion(self):
        convert(lambda name: apps.get_model("community", name), shuffle_seed)

    def test_enrichment_becomes_a_restaurant_and_keeps_reviews(self):
        place = self.enrichment(
            "1", "ChIJa", name="Joe's", business_status="OPERATIONAL"
        )
        PlaceReview.objects.create(place=place, text="Good.")
        self.run_conversion()
        place.refresh_from_db()
        self.assertEqual((place.kind, place.key), (GOOGLE, "google:ChIJa"))
        self.assertEqual(place.reviews.count(), 1)
        restaurant = Restaurant.objects.get(place_id="ChIJa")
        self.assertEqual(restaurant.name, "Joe's")
        self.assertEqual((restaurant.zipcode, restaurant.boro), ("11201", "Brooklyn"))
        self.assertEqual(restaurant.shuffle_seed, shuffle_seed("ChIJa"))

    def test_two_camis_for_one_place_keep_one_row(self):
        self.enrichment("1", "ChIJa")
        self.enrichment("2", "ChIJa")
        self.run_conversion()
        self.assertEqual(PlaceEnrichment.objects.filter(place_id="ChIJa").count(), 1)
        self.assertEqual(Restaurant.objects.count(), 1)

    def test_user_data_is_rekeyed_and_unmapped_rows_dropped(self):
        self.enrichment("1", "ChIJa")
        self.enrichment("2", "ChIJb")
        RecommendationFeedback.objects.create(user_id=7, place_id="1", value=1)
        RecommendationFeedback.objects.create(user_id=7, place_id="999", value=1)
        HealthScore.objects.create(place_id="2", score=0.8)
        HealthScore.objects.create(place_id="999", score=0.1)
        MenuEstimate.objects.create(place_id="1", items=[])
        LocationLookup.objects.create(kind=DOHMH, key="camis:1", found=True)
        self.run_conversion()
        self.assertEqual(
            list(RecommendationFeedback.objects.values_list("place_id", flat=True)),
            ["ChIJa"],
        )
        self.assertEqual(
            list(HealthScore.objects.values_list("place_id", flat=True)), ["ChIJb"]
        )
        self.assertEqual(MenuEstimate.objects.get().place_id, "ChIJa")
        self.assertFalse(LocationLookup.objects.exists())

    def test_pins_move_and_merge_with_existing_google_pins(self):
        self.enrichment("1", "ChIJa")
        old = CommunitySubject.objects.create(kind=DOHMH, key="camis:1", name="Joe")
        UserRating.objects.create(subject=old, user_id=1, score=5)
        UserRating.objects.create(subject=old, user_id=2, score=4)
        UserComment.objects.create(subject=old, user_id=1, text="Yum")
        live = CommunitySubject.objects.create(kind=GOOGLE, key="google:ChIJa")
        UserRating.objects.create(subject=live, user_id=2, score=1)
        CommunitySubject.objects.create(kind=DOHMH, key="camis:404")
        self.run_conversion()
        self.assertEqual(CommunitySubject.objects.count(), 1)
        live.refresh_from_db()
        self.assertEqual(
            dict(live.ratings.values_list("user_id", "score")), {1: 5, 2: 1}
        )
        self.assertEqual(live.comments.get().text, "Yum")
