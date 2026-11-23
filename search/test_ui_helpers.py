from django.test import SimpleTestCase, TestCase

from nycfood.test_utils import ALL_DATABASES
from search import place_panel
from search.find_food import market_hours, market_open_in
from search.score_chips import _clean, _signed, build_chips


class MarketHoursTests(SimpleTestCase):
    def test_parses_common_formats(self):
        self.assertEqual(market_hours("8 a.m. - 3 p.m."), (480, 900))
        self.assertEqual(market_hours("8:30am to noon"), (510, 720))
        self.assertEqual(market_hours("5 PM - midnight"), (1020, 1440))

    def test_bad_or_missing_hours(self):
        self.assertIsNone(market_hours(""))
        self.assertIsNone(market_hours(None))
        self.assertIsNone(market_hours("8 a.m."))
        self.assertIsNone(market_hours("3 p.m. - 8 a.m."))

    def test_open_in_windows(self):
        hours = "8 a.m. - 1 p.m."
        self.assertTrue(market_open_in(hours, "morning"))
        self.assertTrue(market_open_in(hours, "afternoon"))
        self.assertFalse(market_open_in(hours, "evening"))
        self.assertTrue(market_open_in(hours, "now", 9 * 60))
        self.assertFalse(market_open_in(hours, "now", 14 * 60))
        self.assertFalse(market_open_in(hours, "now", None))
        self.assertFalse(market_open_in("", "morning"))


class ScoreChipsTests(SimpleTestCase):
    def test_signed(self):
        self.assertEqual(_signed("+0.20"), 1)
        self.assertEqual(_signed("−0.10"), -1)
        self.assertEqual(_signed("-0.1"), -1)
        self.assertEqual(_signed("0"), 0)
        self.assertEqual(_signed("+0"), 0)
        self.assertEqual(_signed("n/a"), 0)

    def test_clean(self):
        self.assertEqual(_clean("Cuisine (Salads)"), "Salads cuisine")
        self.assertEqual(_clean("AI review score 0.8"), "Reviews sound healthy")
        self.assertEqual(_clean("Review keywords (3)"), "Reviews mention healthy food")
        self.assertEqual(_clean("Fried food (menu)"), "Fried food")

    def test_empty_breakdown(self):
        self.assertEqual(build_chips(None), {"helped": [], "held": [], "notes": []})

    def test_builds_helped_held_and_notes(self):
        breakdown = {
            "has_menu": False,
            "estimated_menu_health": 0.5,
            "parts": [
                {
                    "label": "Rating",
                    "value_0_1": 0.9,
                    "steps": [("Google", "4.6★ (1,200 reviews)")],
                },
                {
                    "label": "Healthy index",
                    "value_0_1": 0.5,
                    "steps": [
                        ("Cuisine (Salads)", "+0.20"),
                        ("Fried food (menu)", "−0.10"),
                        ("AI review score 0.2", "-0.05"),
                        ("Review keywords (2)", "-0.05"),
                        ("AI-estimated menu ~450 kcal", "0.7 good"),
                        ("AI-estimated menu ~1200 kcal", "0.2 high"),
                        ("AI-estimated menu, no number", "0.5"),
                        ("Neutral", "0"),
                    ],
                },
            ],
        }
        chips = build_chips(breakdown)
        self.assertIn("4.6★ from 1,200 reviews", chips["helped"])
        self.assertIn("Salads cuisine", chips["helped"])
        self.assertIn("Meals around 450 kcal", chips["helped"])
        self.assertIn("Fried food", chips["held"])
        self.assertIn("Reviews don't sound very healthy", chips["held"])
        self.assertIn("Reviews mention less healthy food", chips["held"])
        self.assertIn("Meals around 1200 kcal", chips["held"])
        self.assertEqual(chips["notes"], ["Menu is estimated"])

    def test_low_and_middle_rating_and_no_menu(self):
        low = build_chips(
            {"parts": [{"label": "Rating", "value_0_1": 0.2, "steps": []}]}
        )
        self.assertEqual(low["held"], ["Ratings"])
        self.assertEqual(low["notes"], ["No menu data yet"])
        mid = build_chips(
            {
                "has_menu": True,
                "parts": [{"label": "Rating", "value_0_1": 0.5, "steps": []}],
            }
        )
        self.assertEqual(mid["notes"], ["Ratings"])


class PlacePanelHelperTests(SimpleTestCase):
    def test_price_range(self):
        self.assertEqual(place_panel._price_range(None), "")
        self.assertEqual(
            place_panel._price_range(
                {"startPrice": {"units": "10"}, "endPrice": {"units": "20"}}
            ),
            "$10–20 per person",
        )
        self.assertEqual(
            place_panel._price_range({"startPrice": {"units": "15"}}),
            "$15+ per person",
        )
        self.assertEqual(place_panel._price_range({"startPrice": {"units": "x"}}), "")

    def test_directions(self):
        self.assertIn("40.7,-73.9", place_panel._directions(40.7, -73.9, ""))
        self.assertIn("1+Main+St", place_panel._directions(None, None, "1 Main St"))
        self.assertEqual(place_panel._directions(None, None, ""), "")


class PlacePanelContextTests(TestCase):
    databases = ALL_DATABASES

    def test_market_key_gets_basics_only(self):
        ctx = place_panel.panel_context(
            "market:1", name="Union Sq", category="farmers_market", lat=1, lng=2
        )
        self.assertEqual(ctx["kind_label"], "Farmers market")
        self.assertFalse(ctx["is_restaurant"])

    def test_unknown_google_place(self):
        ctx = place_panel.panel_context("google:missing", name="X")
        self.assertEqual(ctx["name"], "X")
        self.assertFalse(ctx["is_restaurant"])
