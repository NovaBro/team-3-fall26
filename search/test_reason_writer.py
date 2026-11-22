"""Tests for the Gemini reason paragraphs (search/reason_writer.py).

Gemini is never called: a fake ``generate`` function stands in for it.

    GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_reason_writer
"""

import io
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from community.keys import DOHMH
from community.models import HealthScore, PlaceEnrichment, PlaceReview, ReasonBlurb
from search import reason_writer, views
from search.models import RestaurantInspection
from nycfood.test_utils import ALL_DATABASES

GOOD = "A salad bar where reviewers praise the crisp greens and grilled chicken."


class PromptTests(SimpleTestCase):
    def test_prompt_holds_only_our_facts(self):
        prompt = reason_writer.build_prompt(
            "GREEN LEAF", "Salads", ["Healthy cuisine (Salads)", "NYC health grade A"]
        )
        self.assertIn("- Healthy cuisine (Salads)", prompt)
        self.assertIn("Cuisine: Salads", prompt)
        self.assertIn("Do not invent", prompt)
        self.assertNotIn("Review lines", prompt)

    def test_version_tag(self):
        tag = reason_writer.model_tag("m")
        self.assertTrue(reason_writer.is_current(tag))
        self.assertFalse(reason_writer.is_current("m"))  # written by the old prompt
        self.assertFalse(reason_writer.is_current(""))

    def test_clean_output(self):
        self.assertEqual(reason_writer.clean_output(f'  "{GOOD}"\n'), GOOD)
        self.assertEqual(reason_writer.clean_output("See https://x.com"), "")
        self.assertEqual(reason_writer.clean_output("   "), "")
        long_text = "Fresh bowls and light dishes here. " * 20
        cleaned = reason_writer.clean_output(long_text)
        self.assertLessEqual(len(cleaned), reason_writer.MAX_CHARS)
        self.assertTrue(cleaned.endswith("."))

    def test_no_reasons_means_no_call(self):
        def boom(prompt):
            raise AssertionError("should not be called")

        self.assertEqual(reason_writer.write_blurb("X", "Y", [], boom), "")

    @override_settings(GEMINI_API_KEY="")
    def test_missing_key_is_a_clear_error(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaisesMessage(RuntimeError, "GEMINI_API_KEY"):
                reason_writer.gemini_generate()


class FakeClientError(Exception):
    code = 429


def fake_genai(answer=None):
    """A stand-in for the google.genai package (no network)."""

    class Models:
        def generate_content(self, model, contents):
            if answer is None:
                raise FakeClientError("RESOURCE_EXHAUSTED")
            return types.SimpleNamespace(text=answer)

    class Client:
        def __init__(self, api_key, http_options=None):
            self.models = Models()

    genai = types.ModuleType("google.genai")
    genai.Client = Client
    google = types.ModuleType("google")
    google.genai = genai
    return {"google": google, "google.genai": genai}


class GeminiWrapperTests(SimpleTestCase):
    def test_tests_never_get_a_live_key(self):
        from django.conf import settings

        self.assertEqual(settings.GEMINI_API_KEY, "")

    def test_returns_text_and_maps_429(self):
        with patch.dict(sys.modules, fake_genai(GOOD)):
            generate = reason_writer.gemini_generate(api_key="k")
            self.assertEqual(generate("hi"), GOOD)
        with patch.dict(sys.modules, fake_genai(None)):
            generate = reason_writer.gemini_generate(api_key="k")
            with self.assertRaises(reason_writer.RateLimited):
                generate("hi")


class WriteReasonsCommandTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        RestaurantInspection.objects.create(
            camis="88",
            dba="GREEN LEAF",
            boro="Queens",
            street="1 Main St",
            zipcode="11101",
            cuisine="Salads",
            inspection_date="2024-07-01",
            grade="A",
        )
        place = PlaceEnrichment.objects.create(
            kind=DOHMH, key="camis:88", camis="88", display_name="Green Leaf"
        )
        PlaceReview.objects.create(place=place, text="Great kale bowl.", rating=5)
        HealthScore.objects.create(camis="88", score=0.8)
        self.prompts = []

    def fake(self, prompt):
        self.prompts.append(prompt)
        return GOOD

    def run_command(self, *args, generate=None):
        out = io.StringIO()
        call_command(
            "write_reasons",
            *args,
            "--sleep",
            "0",
            generate=generate or self.fake,
            stdout=out,
        )
        return out.getvalue()

    def test_saves_once_then_skips_until_refresh(self):
        self.run_command()
        row = ReasonBlurb.objects.get(camis="88")
        self.assertEqual(row.text, GOOD)
        self.assertIn("Healthy cuisine (Salads)", row.facts)
        self.assertNotIn("Great kale bowl.", self.prompts[0])  # no Google text
        self.run_command()  # already written -> no new call
        self.assertEqual(len(self.prompts), 1)
        self.run_command("--refresh")
        self.assertEqual(len(self.prompts), 2)

    def test_dry_run_saves_nothing(self):
        out = self.run_command("--dry-run")
        self.assertIn(GOOD, out)
        self.assertIn("Would save 1", out)
        self.assertFalse(ReasonBlurb.objects.exists())

    def test_rate_limit_stops_cleanly(self):
        def limited(prompt):
            raise reason_writer.RateLimited("429")

        out = self.run_command(generate=limited)
        self.assertIn("rate limit", out)
        self.assertFalse(ReasonBlurb.objects.exists())

    def test_detail_page_gets_the_paragraph(self):
        with patch("search.views.find_restaurant_place", return_value=None):
            url = reverse("search:restaurant_detail", args=["88"])
            self.assertEqual(self.client.get(url).context["reason_blurb"], "")
            ReasonBlurb.objects.create(
                camis="88", text=GOOD, model_name=reason_writer.model_tag("m")
            )
            self.assertEqual(self.client.get(url).context["reason_blurb"], GOOD)
        self.assertEqual(views._reason_blurb("88"), GOOD)

    def test_detail_page_shows_the_paragraph_above_the_list(self):
        ReasonBlurb.objects.create(
            camis="88", text=GOOD, model_name=reason_writer.model_tag("m")
        )
        with patch("search.views.find_restaurant_place", return_value=None):
            page = self.client.get(reverse("search:restaurant_detail", args=["88"]))
        html = page.content.decode()
        self.assertIn(f'<p class="healthiness-score__blurb">{GOOD}</p>', html)
        self.assertLess(
            html.index("healthiness-score__blurb"), html.index("healthiness-score__why")
        )


@override_settings(GEMINI_API_KEY="test-key")
class OnDemandTests(TestCase):
    """The detail page writes the paragraph on the first visit, then reuses it."""

    databases = ALL_DATABASES

    def setUp(self):
        cache.clear()
        RestaurantInspection.objects.create(
            camis="99",
            dba="LEAF BAR",
            boro="Queens",
            street="2 Main St",
            zipcode="11101",
            cuisine="Salads",
            inspection_date="2024-07-01",
            grade="A",
        )
        self.calls = []
        self.url = reverse("search:restaurant_detail", args=["99"])

    def visit(self, generate):
        with patch("search.views.find_restaurant_place", return_value=None), patch(
            "search.reason_writer.live_generate", return_value=generate
        ):
            return self.client.get(self.url).context["reason_blurb"]

    def fake(self, prompt):
        self.calls.append(prompt)
        return GOOD

    def test_first_visit_writes_and_stores_then_reuses(self):
        self.assertEqual(self.visit(self.fake), GOOD)
        self.assertEqual(ReasonBlurb.objects.get(camis="99").text, GOOD)
        self.assertEqual(self.visit(self.fake), GOOD)
        self.assertEqual(len(self.calls), 1)

    def test_no_key_means_no_call(self):
        with override_settings(GEMINI_API_KEY=""):
            self.assertEqual(self.visit(self.fake), "")
        self.assertEqual(self.calls, [])

    def test_old_prompt_paragraph_is_rewritten(self):
        ReasonBlurb.objects.create(camis="99", text="Old text.", model_name="m")
        self.assertEqual(self.visit(self.fake), GOOD)
        self.assertEqual(ReasonBlurb.objects.get(camis="99").text, GOOD)
        with override_settings(GEMINI_API_KEY=""):
            ReasonBlurb.objects.filter(camis="99").update(model_name="m")
            self.assertEqual(self.visit(self.fake), "")  # old text is not shown

    def test_quota_error_pauses_calls(self):
        def limited(prompt):
            self.calls.append(prompt)
            raise reason_writer.RateLimited("429")

        self.assertEqual(self.visit(limited), "")
        self.assertEqual(self.visit(limited), "")
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(ReasonBlurb.objects.exists())

    def test_other_failure_falls_back_to_the_list(self):
        def broken(prompt):
            raise ValueError("network down")

        with self.assertLogs("search.views", level="WARNING"):
            self.assertEqual(self.visit(broken), "")
        self.assertFalse(ReasonBlurb.objects.exists())

    def test_personal_reasons_are_not_sent(self):
        profile = SimpleNamespace(
            weight_lbs=None,
            height_in=None,
            health_goals=[],
            favorite_foods="Salads",
            disliked_foods="",
            home_address="Queens 11101",
            allergies="",
        )
        with patch("search.views._profile_for", return_value=profile), patch(
            "search.views.find_restaurant_place", return_value=None
        ), patch("search.reason_writer.live_generate", return_value=self.fake):
            page = self.client.get(self.url)
        shown = page.context["score_breakdown"]["reasons"]
        self.assertIn("Matches your favorite food (Salad)", shown)
        self.assertNotIn("favorite food", self.calls[0])
        self.assertNotIn("Near your home", self.calls[0])
