"""AI health scores worked out when a place is first shown.

The real model is never loaded: a fake encoder stands in for it.

    GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_ai_scores
"""

import sys
import types
from unittest.mock import patch

import numpy as np
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from community.keys import GOOGLE
from community.models import HealthScore, PlaceEnrichment, PlaceReview
from search import ai_scores, health_ai
from search.test_health_ai import fake_encoder
from nycfood.test_utils import ALL_DATABASES, make_restaurant

HEALTHY = ["Fresh vegetables and grilled chicken, very light and healthy."]


@override_settings(AI_LIVE_SCORING=True)
class AiHealthForTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        cache.clear()

    def test_stored_score_is_reused(self):
        HealthScore.objects.create(
            place_id="1", score=0.9, goal_scores={"low-carb": 0.6}
        )
        with patch.object(ai_scores, "shared_encoder") as encoder:
            self.assertEqual(ai_scores.ai_health_for("1", "X", HEALTHY), 0.9)
            self.assertEqual(
                ai_scores.ai_scores_for("1", "X", HEALTHY), (0.9, {"low-carb": 0.6})
            )
        encoder.assert_not_called()

    def test_old_row_without_goal_scores_gets_them(self):
        HealthScore.objects.create(place_id="8", score=0.9)  # made before goals
        with patch.object(ai_scores, "shared_encoder", return_value=fake_encoder):
            health, goals = ai_scores.ai_scores_for("8", "X", HEALTHY)
        self.assertIsNotNone(health)
        self.assertIn("weight-loss", goals)
        self.assertEqual(HealthScore.objects.get(place_id="8").goal_scores, goals)

    def test_old_row_is_used_as_is_when_live_scoring_is_off(self):
        HealthScore.objects.create(place_id="9", score=0.8)
        with override_settings(AI_LIVE_SCORING=False):
            self.assertEqual(ai_scores.ai_scores_for("9", "X", HEALTHY), (0.8, {}))

    def test_missing_score_is_computed_and_stored(self):
        with patch.object(ai_scores, "shared_encoder", return_value=fake_encoder):
            score = ai_scores.ai_health_for("2", "LEAF", HEALTHY)
        self.assertIsNotNone(score)
        row = HealthScore.objects.get(place_id="2")
        self.assertEqual(row.score, score)
        self.assertIsNotNone(row.goal_scores)

    def test_no_text_or_no_model_gives_none(self):
        with patch.object(ai_scores, "shared_encoder", return_value=fake_encoder):
            self.assertIsNone(ai_scores.ai_health_for("3", "X", []))
        with patch.object(ai_scores, "shared_encoder", return_value=None):
            self.assertIsNone(ai_scores.ai_health_for("4", "X", HEALTHY))
        self.assertFalse(HealthScore.objects.exists())

    def test_text_with_nothing_about_food_is_not_retried(self):
        calls = []

        def counting(texts):
            calls.append(len(texts))
            return fake_encoder(texts)

        with patch.object(ai_scores, "shared_encoder", return_value=counting):
            self.assertIsNone(ai_scores.ai_health_for("5", "X", ["Parking ok."]))
            self.assertIsNone(ai_scores.ai_health_for("5", "X", ["Parking ok."]))
        self.assertEqual(len(calls), 1)

    @override_settings(AI_LIVE_SCORING=False)
    def test_off_switch(self):
        with patch.object(ai_scores, "shared_encoder") as encoder:
            self.assertIsNone(ai_scores.ai_health_for("6", "X", HEALTHY))
        encoder.assert_not_called()

    def test_detail_page_scores_its_reviews(self):
        make_restaurant(
            "7",
            "LEAF",
            boro="Queens",
            street="1 Main St",
            zipcode="11101",
            cuisine="Salads",
        )
        place = PlaceEnrichment.objects.create(
            kind=GOOGLE, key="google:7", place_id="7"
        )
        PlaceReview.objects.create(place=place, text=HEALTHY[0], rating=5)
        with patch.object(ai_scores, "shared_encoder", return_value=fake_encoder):
            page = self.client.get(reverse("search:restaurant_detail", args=["7"]))
        self.assertIsNotNone(page.context["score_breakdown"]["ai_health"])
        self.assertTrue(HealthScore.objects.filter(place_id="7").exists())


class SharedEncoderTests(SimpleTestCase):
    def tearDown(self):
        ai_scores._encoder = None
        ai_scores._failed_at = None

    def test_load_failure_waits_before_retrying(self):
        ai_scores._encoder = ai_scores._failed_at = None
        with patch.object(
            health_ai, "load_encoder", side_effect=RuntimeError("no model")
        ) as load:
            with self.assertLogs("search.ai_scores", level="WARNING"):
                self.assertIsNone(ai_scores.shared_encoder())
            self.assertIsNone(ai_scores.shared_encoder())
        self.assertEqual(load.call_count, 1)

    def test_loads_once(self):
        ai_scores._encoder = ai_scores._failed_at = None
        with patch.object(health_ai, "load_encoder", return_value=fake_encoder) as load:
            ai_scores.shared_encoder()
            ai_scores.shared_encoder()
        self.assertEqual(load.call_count, 1)


class FastembedBackendTests(SimpleTestCase):
    def test_fastembed_is_used_when_installed(self):
        class FakeModel:
            def __init__(self, name, cache_dir=None):
                self.name = name

            def embed(self, texts, batch_size=64):
                for text in texts:
                    yield np.ones(4) * len(text)

        module = types.ModuleType("fastembed")
        module.TextEmbedding = FakeModel
        with patch.dict(sys.modules, {"fastembed": module}):
            encode = health_ai.load_encoder("all-MiniLM-L6-v2", "auto")
            vectors = encode(["ab", "abc"])
        self.assertEqual(vectors.shape, (2, 4))
