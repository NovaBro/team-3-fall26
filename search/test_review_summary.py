"""Google's own AI review summary (Places API ``reviewSummary``).

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_review_summary
"""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from community.keys import DOHMH
from community.models import PlaceEnrichment, PlaceReview
from search.models import RestaurantInspection
from search.services import places

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
    databases = {"default", "community"}

    def place(self, raw):
        return PlaceEnrichment.objects.create(
            kind=DOHMH,
            key="camis:1",
            camis="1",
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
    databases = {"default", "community"}

    def setUp(self):
        RestaurantInspection.objects.create(
            camis="1",
            dba="LEAF BAR",
            boro="Queens",
            street="2 Main St",
            zipcode="11101",
            cuisine="Salads",
            inspection_date="2024-07-01",
            grade="A",
        )
        self.place = PlaceEnrichment.objects.create(
            kind=DOHMH, key="camis:1", camis="1", raw_json={}
        )
        PlaceReview.objects.create(place=self.place, text="Raw review text.", rating=5)

    def html(self):
        with patch("search.views.find_restaurant_place", return_value=None):
            url = reverse("search:restaurant_detail", args=["1"])
            return self.client.get(url).content.decode()

    def test_summary_replaces_the_review_list(self):
        self.place.raw_json = {"reviewSummary": SUMMARY}
        self.place.save()
        html = self.html()
        self.assertIn("Review summary", html)
        self.assertIn(SUMMARY["text"]["text"], html)
        self.assertIn("Summarized with Gemini", html)
        self.assertIn(SUMMARY["reviewsUri"], html)
        self.assertIn("Report this summary", html)
        self.assertNotIn("Raw review text.", html)

    def test_without_summary_the_reviews_stay(self):
        html = self.html()
        self.assertNotIn("Review summary", html)
        self.assertIn("Raw review text.", html)
