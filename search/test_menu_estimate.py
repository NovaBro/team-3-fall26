"""Gemini-estimated menus: parsing, storage, command, ranking and Menu box.

Gemini is never called: the command takes a fake ``generate``.
"""

import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from community.models import MenuEstimate
from search import menu_estimate as me
from search import what_to_order as wto
from search.menustat import clear_menustat_cache
from search.models import MenuItem, RestaurantSummary
from search.recommend import ESTIMATE_SHARE, UNLINKED_WEIGHTS, score_restaurant


def item(name, kind="main", calories=500, description=""):
    return {
        "name": name,
        "kind": kind,
        "calories": calories,
        "description": description,
    }


def mains(*kcals):
    return [item(f"Dish number {i}", calories=k) for i, k in enumerate(kcals)]


def answer(entries):
    return json.dumps(
        {"restaurants": [{"id": i, "items": items} for i, items in entries]}
    )


class ParseAndCleanTests(SimpleTestCase):
    def test_parse_answer_maps_ids_to_items(self):
        text = answer([("1", [item("Pasta")]), ("2", [item("Soup")])])
        self.assertEqual(set(me.parse_answer(text)), {"1", "2"})

    def test_parse_answer_bad_json_is_empty(self):
        self.assertEqual(me.parse_answer("not json"), {})
        self.assertEqual(me.parse_answer('{"restaurants": "x"}'), {})

    def test_clean_drops_bad_kinds_names_and_dupes_and_clamps_kcal(self):
        cleaned = me.clean_items(
            [
                item("Chicken  bowl", calories="640"),
                item("chicken bowl"),  # duplicate (case-insensitive)
                item("ab"),  # too short
                item("Menu header", kind="header"),
                item("Giant platter", calories=99999),
                item("Mystery", calories="lots"),
            ]
        )
        self.assertEqual(
            [(i["name"], i["calories"]) for i in cleaned],
            [("Chicken bowl", 640), ("Giant platter", me.MAX_KCAL), ("Mystery", None)],
        )

    def test_summarize_uses_mains_only_and_needs_three(self):
        items = me.clean_items(
            mains(400, 600, 800) + [item("Big soda", kind="drink", calories=300)]
        )
        self.assertEqual(me.summarize(items), (600.0, 3))
        self.assertEqual(me.summarize(me.clean_items(mains(400, 600))), (None, 2))

    def test_estimate_batch_keeps_only_requested_ids(self):
        text = answer([("1", mains(500)), ("99", mains(500))])
        result = me.estimate_batch([{"id": "1", "name": "A"}], lambda _p: text)
        self.assertEqual(list(result), ["1"])

    def test_prompt_lists_each_restaurant(self):
        prompt = me.build_prompt(
            [{"id": "7", "name": "Joe's", "cuisine": "Pizza", "boro": "Queens"}]
        )
        self.assertIn('"id": "7"', prompt)
        self.assertIn("Pizza", prompt)


class StoredEstimateTests(TestCase):
    databases = {"default", "community"}

    def save(self, camis="1", median=500.0, tag=None, items=None):
        MenuEstimate.objects.create(
            camis=camis,
            items=items or me.clean_items(mains(500, 500, 500)),
            median_calories=median,
            meal_count=3,
            model_name=tag or me.model_tag("m"),
        )

    def test_nutrition_from_stored_estimate(self):
        self.save(median=500.0)
        info = me.estimate_nutrition_for_camis("1")
        self.assertAlmostEqual(info["score"], 0.5)
        self.assertEqual(info["meal_count"], 3)

    def test_stale_prompt_version_is_ignored(self):
        self.save(tag="m|v0")
        self.assertIsNone(me.estimate_nutrition_for_camis("1"))
        self.assertEqual(me.estimated_items("1"), [])

    def test_no_median_means_no_nutrition(self):
        self.save(median=None)
        self.assertIsNone(me.estimate_nutrition_for_camis("1"))
        self.assertTrue(me.estimated_items("1"))


class EstimateMenusCommandTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        for camis, name in (
            ("1", "JOE'S PIZZA"),
            ("2", "GREEN BOWL"),
            ("3", "CHAIN X"),
        ):
            RestaurantSummary.objects.create(camis=camis, name=name, cuisine="Pizza")
        # CHAIN X has a MenuStat menu (3 qualifying meals) and is skipped.
        for n in range(3):
            MenuItem.objects.create(
                restaurant="Chain X",
                year=2018,
                menu_item_id=str(n),
                item_name=f"Meal {n}",
                food_category="Entrees",
                calories=500,
                protein=20,
            )
        self.prompts = []
        clear_menustat_cache()
        self.addCleanup(clear_menustat_cache)

    def fake(self, prompt):
        self.prompts.append(prompt)
        ids = [
            json.loads(line)["id"]
            for line in prompt.splitlines()
            if line.startswith("{")
        ]
        return answer([(i, mains(400, 500, 600)) for i in ids])

    def run_cmd(self, *args, generate=None):
        out = StringIO()
        call_command(
            "estimate_menus",
            *args,
            "--sleep",
            "0",
            generate=generate or self.fake,
            stdout=out,
        )
        return out.getvalue()

    def test_saves_non_menustat_restaurants(self):
        out = self.run_cmd()
        self.assertEqual(
            sorted(MenuEstimate.objects.values_list("camis", flat=True)), ["1", "2"]
        )
        row = MenuEstimate.objects.get(camis="1")
        self.assertEqual((row.median_calories, row.meal_count), (500.0, 3))
        self.assertTrue(me.is_current(row.model_name))
        self.assertIn("Saved 2 estimates", out)

    def test_dry_run_saves_nothing(self):
        self.run_cmd("--dry-run")
        self.assertFalse(MenuEstimate.objects.exists())

    def test_batches_and_skips_done(self):
        self.run_cmd("--batch", "1")
        self.assertEqual(len(self.prompts), 2)
        self.prompts.clear()
        self.run_cmd()
        self.assertEqual(self.prompts, [])  # nothing left
        self.run_cmd("--refresh")
        self.assertEqual(len(self.prompts), 1)

    def test_stops_on_rate_limit(self):
        def limited(_prompt):
            raise me.RateLimited("429")

        out = self.run_cmd(generate=limited)
        self.assertIn("rate limit", out)
        self.assertFalse(MenuEstimate.objects.exists())


class ScoringTests(SimpleTestCase):
    base = dict(name="Some Place", cuisine="American", grade="A")

    def test_estimate_blends_with_prior_at_low_confidence(self):
        _, _, plain = score_restaurant(**self.base)
        score, tags, bd = score_restaurant(
            **self.base, estimated_menu_score=1.0, estimated_median_kcal=200
        )
        h = plain["prior_health"]
        expected = ESTIMATE_SHARE * 1.0 + (1 - ESTIMATE_SHARE) * h
        self.assertAlmostEqual(bd["health_estimate"], 100 * expected)
        self.assertEqual(bd["confidence"], "low")
        self.assertFalse(bd["has_menu"])
        self.assertEqual(bd["parts"][0]["weight"], UNLINKED_WEIGHTS[0])
        self.assertAlmostEqual(bd["parts"][0]["value_0_1"], expected)
        self.assertGreater(score, plain["total"])
        self.assertNotIn("Menu-based estimate", tags)
        self.assertNotIn("Lower-calorie menu", tags)
        self.assertIn("Lighter dishes on its estimated menu", bd["reasons"])

    def test_heavy_estimate_lowers_score(self):
        plain, _, _ = score_restaurant(**self.base)
        heavy, _, _ = score_restaurant(**self.base, estimated_menu_score=0.0)
        self.assertLess(heavy, plain)

    def test_non_meal_cuisine_ignores_estimate(self):
        donuts = dict(name="Donut Shop", cuisine="Donuts", grade="A")
        plain, _, _ = score_restaurant(**donuts)
        est, _, bd = score_restaurant(**donuts, estimated_menu_score=0.9)
        self.assertAlmostEqual(plain, est)
        self.assertIsNone(bd["estimated_menu_health"])

    def test_menustat_wins_over_estimate(self):
        a, _, bd_a = score_restaurant(**self.base, calorie_score=0.8)
        b, _, bd_b = score_restaurant(
            **self.base, calorie_score=0.8, estimated_menu_score=0.0
        )
        self.assertAlmostEqual(a, b)
        self.assertIsNone(bd_b["estimated_menu_health"])


class MenuBoxTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        MenuEstimate.objects.create(
            camis="9",
            items=me.clean_items(
                mains(500, 600, 700) + [item("Lemonade", kind="drink", calories=150)]
            ),
            median_calories=600,
            meal_count=3,
            model_name=me.model_tag("m"),
        )

    def test_estimate_is_last_fallback(self):
        with patch.object(wto, "menustat_dishes", return_value=[]), patch.object(
            wto, "photo_dishes", return_value=[]
        ):
            result = wto.build("X", None, None, "X", camis="9")
        self.assertEqual(result.source, "estimate")
        self.assertEqual([g.label for g in result.groups], ["Food", "Drinks"])
        self.assertEqual(result.groups[0].dishes[0].calories, 500)

    def test_photos_win_over_estimate(self):
        with patch.object(wto, "menustat_dishes", return_value=[]), patch.object(
            wto, "photo_dishes", return_value=[wto.Dish("Real dish")]
        ):
            result = wto.build("X", None, None, "X", camis="9")
        self.assertEqual(result.source, "photos")

    def test_estimate_used_when_photo_reading_fails(self):
        with patch.object(wto, "menustat_dishes", return_value=[]), patch.object(
            wto, "photo_dishes", side_effect=RuntimeError("boom")
        ):
            result = wto.build("X", None, None, "X", camis="9")
        self.assertEqual(result.source, "estimate")

    def test_no_estimate_keeps_message(self):
        with patch.object(wto, "menustat_dishes", return_value=[]), patch.object(
            wto, "photo_dishes", return_value=[]
        ):
            result = wto.build("X", None, None, "X", camis="404")
        self.assertEqual(result.message, "Menu not available.")


class Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": self.text}]}}]}


class RetryTests(SimpleTestCase):
    def test_busy_server_is_retried(self):
        responses = [Resp(503), Resp(503), Resp(200, "{}")]
        waits = []
        with patch.object(
            me.requests, "post", side_effect=lambda *a, **k: responses.pop(0)
        ):
            text = me.gemini_generate("m", "k", sleep=waits.append)("hi")
        self.assertEqual(text, "{}")
        self.assertEqual(waits, list(me.RETRY_WAITS[:2]))

    def test_gives_up_after_retries(self):
        with patch.object(me.requests, "post", return_value=Resp(503)):
            with self.assertRaises(RuntimeError):
                me.gemini_generate("m", "k", sleep=lambda _s: None)("hi")

    def test_quota_is_not_retried(self):
        post_calls = []

        def post(*a, **k):
            post_calls.append(1)
            return Resp(429)

        with patch.object(me.requests, "post", side_effect=post):
            with self.assertRaises(me.RateLimited):
                me.gemini_generate("m", "k", sleep=lambda _s: None)("hi")
        self.assertEqual(len(post_calls), 1)
