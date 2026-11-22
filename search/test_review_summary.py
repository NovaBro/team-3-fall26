"""Google's own AI review summary (Places API ``reviewSummary``).

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_review_summary
"""

from django.test import TestCase
from django.urls import reverse

from community.keys import GOOGLE
from community.models import PlaceEnrichment, PlaceReview
from search.services import places
from nycfood.test_utils import ALL_DATABASES, make_restaurant

SUMMARY = {
    "text": {
        "text": "People say the bowls are fresh and filling.",
        "languageCode": "en",
    },
    "disclosureText": {"text": "Summarized with Gemini", "languageCode": "en"},
    "reviewsUri": "https://www.google.com/maps/place//data=reviews",
    "flagContentUri": "https://www.google.com/local/review/rap/report?x",
}


class ReviewSummaryTests(TestCase):
    databases = ALL_DATABASES

    def place(self, raw):
        return PlaceEnrichment.objects.create(
            kind=GOOGLE,
            key="google:1",
            place_id="1",
            google_maps_uri="https://maps.google.com/?cid=1",
            raw_json=raw,
        )

    def test_details_request_asks_for_it(self):
        self.assertIn("reviewSummary", places.DETAILS_FIELD_MASK.split(","))

    def test_summary_fields(self):
        summary = self.place({"reviewSummary": SUMMARY}).review_summary
        self.assertEqual(summary["text"], SUMMARY["text"]["text"])
        self.assertEqual(summary["disclosure"], "Summarized with Gemini")
        self.assertEqual(summary["reviews_uri"], SUMMARY["reviewsUri"])
        self.assertEqual(summary["flag_uri"], SUMMARY["flagContentUri"])

    def test_missing_summary_is_none(self):
        place = self.place({})
        self.assertIsNone(place.review_summary)
        place.raw_json = None
        self.assertIsNone(place.review_summary)

    def test_falls_back_to_maps_link(self):
        raw = {"reviewSummary": {"text": {"text": "Good."}}}
        summary = self.place(raw).review_summary
        self.assertEqual(summary["reviews_uri"], "https://maps.google.com/?cid=1")
        self.assertEqual(summary["disclosure"], "Summarized with Gemini")


class DetailPageSummaryTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        make_restaurant("1", "LEAF BAR", boro="Queens", cuisine="Salads")
        self.place = PlaceEnrichment.objects.create(
            kind=GOOGLE, key="google:1", place_id="1", raw_json={}
        )
        PlaceReview.objects.create(place=self.place, text="Raw review text.", rating=5)

    def html(self):
        url = reverse("search:restaurant_detail", args=["1"])
        return self.client.get(url).content.decode()

    def test_reviews_and_summary_are_not_shown(self):
        # The detail page shows the Menu box instead of Google reviews.
        self.place.raw_json = {"reviewSummary": SUMMARY}
        self.place.save()
        html = self.html()
        self.assertNotIn("Review summary", html)
        self.assertNotIn(SUMMARY["text"]["text"], html)
        self.assertNotIn("Raw review text.", html)
        self.assertIn('id="what-to-order"', html)
