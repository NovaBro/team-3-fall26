"""AI health score: sentence scoring, storage, and use in the Top Picks score.

The real model (sentence-transformers) is not installed in CI, so these tests
use a tiny bag-of-words encoder that behaves the same way: sentences sharing
words with an anchor are "close" to it.
"""

import re
import zlib
from unittest.mock import patch

import numpy as np
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from community.keys import GOOGLE
from community.models import HealthScore, PlaceEnrichment, PlaceReview
from search import health_ai, views
from search.recommend import health_score, score_restaurant
from nycfood.test_utils import ALL_DATABASES, make_restaurant

DIM = 512


def fake_encoder(texts):
    """Hashed bag-of-words vectors (stand-in for a sentence-embedding model)."""
    rows = np.zeros((len(texts), DIM))
    for i, text in enumerate(texts):
        for word in re.findall(r"[a-z]+", text.lower()):
            if len(word) > 3:  # skip "and", "the", "with", ...
                rows[i, zlib.crc32(word.encode()) % DIM] += 1.0
    return rows


class SentenceScoreTests(SimpleTestCase):
    def test_healthy_unhealthy_and_off_topic(self):
        healthy, unhealthy, off_topic = health_ai.sentence_scores(
            [
                "The salad was fresh with lots of vegetables",
                "Greasy fried chicken and french fries",
                "Parking was easy and staff were kind",
            ],
            fake_encoder,
        )
        self.assertGreater(healthy, 0.9)
        self.assertLess(unhealthy, 0.1)
        self.assertIsNone(off_topic)

    def test_split_sentences(self):
        parts = health_ai.split_sentences("Great salad! Fried stuff too.\nOk")
        self.assertEqual(parts, ["Great salad!", "Fried stuff too."])

    def test_restaurant_score_is_pulled_toward_neutral(self):
        one, used_one = health_ai.restaurant_score(
            ["Fresh salad with vegetables."], fake_encoder
        )
        many, used_many = health_ai.restaurant_score(
            ["Fresh salad with vegetables."] * 10, fake_encoder
        )
        self.assertEqual((used_one, used_many), (1, 10))
        self.assertTrue(0.5 < one < many <= 1.0)

    def test_no_health_text_gives_none(self):
        self.assertEqual(
            health_ai.restaurant_score(["Nice staff. Quick service."], fake_encoder),
            (None, 0),
        )


class AiInScoreTests(SimpleTestCase):
    def test_ai_score_replaces_keyword_reviews(self):
        reviews = [{"text": "greasy"}] * 5  # keywords alone would say unhealthy
        self.assertAlmostEqual(health_score("", reviews, "X", ai_score=0.9), 0.9)
        self.assertAlmostEqual(health_score("", reviews, "X", ai_score=0.5), 0.5)
        self.assertLess(health_score("", reviews, "X"), 0.5)

    def test_breakdown_marks_ai(self):
        _s, _t, with_ai = score_restaurant(name="X", ai_health=0.8)
        _s, _t, without = score_restaurant(name="X")
        self.assertEqual(with_ai["parts"][0]["label"], "Health (AI)")
        self.assertEqual(with_ai["ai_health"], 0.8)
        self.assertEqual(without["parts"][0]["label"], "Health")


class StoredScoreTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        make_restaurant(
            "77",
            "GREEN LEAF",
            boro="Queens",
            street="1 Main St",
            zipcode="11101",
            cuisine="American",
        )
        place = PlaceEnrichment.objects.create(
            kind=GOOGLE, key="google:77", place_id="77", display_name="Green Leaf"
        )
        for text in (
            "Fresh salad with lots of vegetables.",
            "Grilled fish and steamed vegetables, very light.",
            "Friendly staff.",
        ):
            PlaceReview.objects.create(place=place, text=text, rating=5)

    def run_command(self, *args):
        with patch("search.health_ai.load_encoder", return_value=fake_encoder):
            call_command("score_health", *args, stdout=open("/dev/null", "w"))

    def test_command_stores_scores_and_skips_done(self):
        self.run_command()
        row = HealthScore.objects.get(place_id="77")
        self.assertAlmostEqual(row.score, 0.7, places=3)
        self.assertEqual(row.sentences_used, 2)
        HealthScore.objects.filter(place_id="77").update(score=0.1)
        self.run_command()  # already scored -> untouched
        self.assertEqual(HealthScore.objects.get(place_id="77").score, 0.1)
        self.run_command("--refresh")
        self.assertAlmostEqual(
            HealthScore.objects.get(place_id="77").score, 0.7, places=3
        )

    def test_views_read_the_stored_score(self):
        self.assertEqual(views._ai_scores("77"), (None, {}))
        HealthScore.objects.create(place_id="77", score=0.9, goal_scores={})
        self.assertEqual(views._ai_scores("77"), (0.9, {}))
        page = self.client.get(reverse("search:restaurant_detail", args=["77"]))
        self.assertEqual(page.context["score_breakdown"]["ai_health"], 0.9)
