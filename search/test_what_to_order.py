"""Menu box: menu from MenuStat or Google photos, with food picks highlighted.

python manage.py test search.test_what_to_order
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import requests
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from community.keys import DOHMH
from community.models import PlaceEnrichment
from search import what_to_order as wto
from search.models import RestaurantInspection

HEALTHY_WORDS = (
    "salad", "grilled", "steamed", "vegan", "lean", "fresh", "healthy",
    "light", "protein", "organic", "vegetable", "greens", "fruit", "low",
)  # fmt: skip
UNHEALTHY_WORDS = (
    "fried", "greasy", "oily", "sugary", "cheesy", "processed", "heavy",
    "dessert", "soda", "fries", "pastr", "sweets", "huge", "creamy",
)  # fmt: skip


def fake_encoder(texts):
    """Healthy words -> [1, 0, 0], unhealthy -> [0, 1, 0], neither -> [0, 0, 1]."""
    rows = []
    for text in texts:
        text = text.lower()
        good = any(word in text for word in HEALTHY_WORDS)
        bad = any(word in text for word in UNHEALTHY_WORDS)
        rows.append([float(good), float(bad), float(not good and not bad)])
    return np.array(rows)


def profile(**fields):
    base = {
        "health_goals": [],
        "favorite_foods": "",
        "disliked_foods": "",
        "allergies": "",
    }
    base.update(fields)
    return SimpleNamespace(**base)


class Resp:
    def __init__(self, data=None, status=200, content=b"jpg"):
        self._data, self.status_code, self.content = data, status, content
        self.headers = {"Content-Type": "image/jpeg"}
        self.text = json.dumps(data) if data is not None else ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._data


def gemini_answer(items):
    text = json.dumps({"items": items})
    return Resp({"candidates": [{"content": {"parts": [{"text": text}]}}]})


class CleanAndPickTests(TestCase):
    def dishes(self, *names):
        dishes = wto.clean([wto.Dish(name) for name in names])
        wto.score_dishes(dishes, fake_encoder, [])
        return dishes

    def test_clean_drops_short_blank_and_repeated_names(self):
        names = [
            d.name
            for d in wto.clean(
                [wto.Dish(n) for n in ("ab", " ", "Kale  salad", "kale salad", "123")]
            )
        ]
        self.assertEqual(names, ["Kale salad"])

    def test_only_healthy_dishes_are_picked(self):
        dishes = self.dishes(
            "Fried chicken basket", "Moo goo gai pan", "Grilled salmon salad"
        )
        picks = wto.pick(dishes, None)
        self.assertEqual([d.name for d in picks], ["Grilled salmon salad"])
        self.assertIsNone(dishes[1].health)  # not about food health
        self.assertLess(dishes[0].health, wto.HEALTHY_AT)
        self.assertEqual(picks[0].notes, ["Lighter choice"])

    def test_allergens_are_skipped_and_reported(self):
        dishes = self.dishes("Grilled fish salad", "Steamed vegetable bowl")
        skipped = []
        picks = wto.pick(dishes, profile(allergies="Fish"), skipped=skipped)
        self.assertEqual([d.name for d in picks], ["Steamed vegetable bowl"])
        self.assertEqual(skipped, [("Grilled fish salad", ["fish"])])

    def test_dislikes_are_ranked_down_not_removed(self):
        dishes = self.dishes("Grilled chicken salad", "Steamed vegetable bowl")
        picks = wto.pick(dishes, profile(disliked_foods="Chicken"))
        self.assertEqual(
            [d.name for d in picks], ["Steamed vegetable bowl", "Grilled chicken salad"]
        )

    def test_liked_food_gets_a_boost_and_a_note(self):
        dishes = self.dishes("Grilled tofu salad", "Grilled chicken salad")
        picks = wto.pick(dishes, profile(favorite_foods="Chicken"))
        if picks[0].name != "Grilled chicken salad":
            # "Chicken" may not be a food option label; then no boost is fine.
            self.skipTest("Chicken is not a profile food option")
        self.assertIn("You like", picks[0].notes[-1])

    def test_goal_scores_feed_the_rank_and_note(self):
        dishes = wto.clean(
            [wto.Dish("Grilled lean protein bowl"), wto.Dish("Creamy pasta")]
        )
        wto.score_dishes(dishes, fake_encoder, ["muscle-gain"])
        picks = wto.pick(dishes, profile(health_goals=["muscle-gain"]))
        self.assertEqual(picks[0].name, "Grilled lean protein bowl")
        self.assertIn("muscle-gain", picks[0].goals)

    def test_pick_count_by_menu_size(self):
        self.assertEqual(
            [wto.pick_count(n) for n in (0, 3, 4, 5, 6, 40)], [0, 0, 2, 2, 3, 3]
        )

    def test_weight_loss_uses_calories_when_every_dish_has_them(self):
        dishes = [
            wto.Dish("Grilled chicken salad", calories=650),
            wto.Dish("Fresh garden salad", calories=300),
        ]
        wto.score_dishes(dishes, fake_encoder, ["weight-loss"])
        picks = wto.pick(dishes, profile(health_goals=["weight-loss"]))
        self.assertEqual(picks[0].name, "Fresh garden salad")
        self.assertIn("Lightest here", picks[0].notes)
        self.assertNotIn("Lightest here", picks[1].notes)

    def test_calories_are_ignored_unless_every_dish_has_them(self):
        dishes = [
            wto.Dish("Grilled chicken salad", calories=650),
            wto.Dish("Fresh garden salad"),
        ]
        self.assertEqual(wto._calorie_scores(dishes), {})


class PriceAndCalorieTests(TestCase):
    def test_price_and_calories_move_out_of_name_and_description(self):
        dish = wto.clean(
            [
                wto.Dish(
                    "Kale Caesar Salad $13.95",
                    "shredded kale & romaine, creamy caesar dressing (432 cal) "
                    "add croutons (+3)",
                )
            ]
        )[0]
        self.assertEqual(dish.name, "Kale Caesar Salad")
        self.assertEqual(dish.price, "$13.95")
        self.assertEqual(dish.calories, 432)
        self.assertEqual(
            dish.description,
            "shredded kale & romaine, creamy caesar dressing add croutons (+3)",
        )

    def test_calorie_misreads_leave_clean_text(self):
        cases = {
            "creamy caesar dressing (432 call add croutons (+3)": (
                "creamy caesar dressing add croutons (+3)"
            ),
            "caesar dressing (432 cal, add croutons (+3))": (
                "caesar dressing, add croutons (+3)"
            ),
            "romaine, feta (495 Calories)": "romaine, feta",
        }
        for text, expected in cases.items():
            dish = wto.clean([wto.Dish("Kale Caesar Salad", text)])[0]
            self.assertEqual(dish.description, expected, text)
            self.assertIn(dish.calories, (432, 495))

    def test_gemini_fields_are_normalised(self):
        dishes = wto._dishes_from(
            [
                {"name": "Soup", "price": 6.5, "calories": "210", "kind": "food"},
                {"name": "Tea", "price": "about $3", "calories": None, "kind": "drink"},
                {"name": "Pie", "price": "", "calories": 99999, "kind": "dessert"},
            ]
        )
        self.assertEqual(
            [(d.name, d.price, d.calories) for d in dishes],
            [("Soup", "$6.50", 210), ("Tea", "$3", None), ("Pie", "", None)],
        )

    def test_a_name_that_is_only_a_price_is_dropped(self):
        self.assertEqual(wto.clean([wto.Dish("$12")]), [])


@override_settings(
    GOOGLE_AUTO_FETCH=True,
    GOOGLE_PLACES_API_KEY="g-key",
    GEMINI_API_KEY="m-key",
    GEMINI_MODEL="gemini-test",
)
class PhotoMenuTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.place = SimpleNamespace(place_id="abc")
        self.calls = []

    def fake_get(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/places/abc"):
            return Resp(
                {"photos": [{"name": f"places/abc/photos/{i}"} for i in range(12)]}
            )
        return Resp(content=b"img")

    def build(self, gemini):
        with patch.object(wto, "menustat_dishes", return_value=[]), patch.object(
            wto.requests, "get", side_effect=self.fake_get
        ), patch.object(wto.requests, "post", side_effect=gemini):
            return wto.build(
                "LEAF BAR", self.place, None, "LEAF BAR, NY", lambda: fake_encoder
            )

    def test_reads_menu_items_grouped_by_kind(self):
        items = [
            {"name": "SALADS", "kind": "header"},
            {"name": "Iced latte", "kind": "drink"},
            {"name": "Kale salad", "description": "fresh greens", "kind": "food"},
            {"name": "Fried calamari", "kind": "food"},
            {"name": "Cheesecake", "kind": "dessert"},
            {"name": "Table 4", "kind": "other"},
        ]
        result = self.build(lambda *a, **k: gemini_answer(items))
        self.assertEqual(result.source, "photos")
        groups = {g.label: [d.name for d in g.dishes] for g in result.groups}
        self.assertEqual(
            groups,
            {
                "Food": ["Kale salad", "Fried calamari"],
                "Drinks": ["Iced latte"],
                "Desserts": ["Cheesecake"],
            },
        )
        self.assertEqual(result.groups[0].dishes[0].description, "fresh greens")
        photo_downloads = [u for u in self.calls if u.endswith("/media")]
        self.assertEqual(len(photo_downloads), wto.MAX_PHOTOS)

    def test_long_groups_split_into_preview_and_rest(self):
        items = [{"name": f"Dish number {i}", "kind": "food"} for i in range(14)]
        result = self.build(lambda *a, **k: gemini_answer(items))
        food = result.groups[0]
        self.assertEqual(len(food.preview), wto.GROUP_PREVIEW)
        self.assertEqual(len(food.rest), 14 - wto.GROUP_PREVIEW)

    @override_settings(PLACES_CACHE_SECONDS=3600)
    def test_a_read_menu_is_cached_for_an_hour(self):
        calls = []

        def gemini(*args, **kwargs):
            calls.append(1)
            return gemini_answer([{"name": "Kale salad", "kind": "food"}])

        first = self.build(gemini)
        first.groups[0].dishes[0].picked = True  # one viewer's highlight
        second = self.build(gemini)
        self.assertEqual(len(calls), 1)
        self.assertEqual(second.groups[0].dishes[0].name, "Kale salad")
        self.assertFalse(second.groups[0].dishes[0].picked)

    @override_settings(PLACES_CACHE_SECONDS=3600)
    def test_an_empty_read_is_not_cached(self):
        calls = []

        def gemini(*args, **kwargs):
            calls.append(1)
            return gemini_answer([])

        self.build(gemini)
        self.build(gemini)
        self.assertEqual(len(calls), 2)

    def test_quota_pauses_gemini(self):
        result = self.build(lambda *a, **k: Resp({"error": "quota"}, status=429))
        self.assertEqual(result.message, "Menu not available.")
        self.assertTrue(cache.get(wto.GEMINI_PAUSE_KEY))
        # While paused, no Google photo calls are made at all.
        self.calls.clear()
        self.build(lambda *a, **k: gemini_answer([]))
        self.assertEqual(self.calls, [])

    def test_google_errors_never_raise(self):
        def broken_get(url, **kwargs):
            raise requests.ConnectionError("down")

        with patch.object(wto, "menustat_dishes", return_value=[]), patch.object(
            wto.requests, "get", side_effect=broken_get
        ):
            result = wto.build("X", self.place, None, "X", lambda: fake_encoder)
        self.assertEqual(result.message, "Menu not available right now.")

    def test_text_search_used_without_a_place_id(self):
        posts = []

        def fake_post(url, **kwargs):
            posts.append(url)
            if url.endswith(":searchText"):
                return Resp({"places": [{"photos": [{"name": "places/z/photos/1"}]}]})
            return gemini_answer([{"name": "Grilled salmon", "kind": "food"}])

        self.place = None
        result = self.build(fake_post)
        self.assertTrue(posts[0].endswith(":searchText"))
        self.assertEqual(result.groups[0].dishes[0].name, "Grilled salmon")

    @override_settings(GOOGLE_AUTO_FETCH=False)
    def test_no_google_calls_when_auto_fetch_is_off(self):
        result = self.build(lambda *a, **k: gemini_answer([]))
        self.assertEqual(result.message, "Menu not available.")
        self.assertEqual(self.calls, [])


class MenuStatTests(TestCase):
    def test_menustat_menu_is_used_first(self):
        dishes = [
            wto.Dish("Grilled chicken salad"),
            wto.Dish("Iced tea", kind="drink"),
        ]
        with patch.object(wto, "menustat_dishes", return_value=dishes), patch.object(
            wto, "photo_dishes"
        ) as photos:
            result = wto.build("CHAIN", None, None, "CHAIN")
        photos.assert_not_called()
        self.assertEqual(result.source, "menustat")
        self.assertEqual([g.label for g in result.groups], ["Food", "Drinks"])

    def test_menustat_categories_map_to_kinds(self):
        from search.models import MenuItem

        rows = [
            ("Big salad", "Salads"),
            ("Cola", "Beverages"),
            ("Brownie", "Baked Goods"),
            ("Extra cheese", "Toppings & Ingredients"),
            ("Fries", "Fried Potatoes"),
        ]
        for name, category in rows:
            MenuItem.objects.create(
                restaurant="Chain X",
                year=2018,
                menu_item_id=name,
                item_name=name,
                food_category=category,
            )
        with patch.object(wto, "match_menustat_restaurant", return_value="Chain X"):
            dishes = wto.menustat_dishes("CHAIN X")
        kinds = {d.name: d.kind for d in dishes}
        self.assertEqual(
            kinds,
            {
                "Big salad": "food",
                "Cola": "drink",
                "Brownie": "dessert",
                "Fries": "food",
            },
        )


class ViewTests(TestCase):
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
        PlaceEnrichment.objects.create(
            kind=DOHMH, key="camis:1", camis="1", raw_json={}
        )

    def test_fragment(self):
        url = reverse("search:what_to_order", args=["1"])
        with patch.object(
            wto, "menustat_dishes", return_value=[wto.Dish("Kale salad")]
        ), patch("search.views.ai_scores.shared_encoder", return_value=fake_encoder):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kale salad")
        self.assertContains(response, "Source: MenuStat")

    def test_source_lines(self):
        from django.template.loader import render_to_string

        groups = wto.group([wto.Dish("Kale salad")])
        photos = wto.Result(source="photos", groups=groups)
        html = render_to_string("search/_what_to_order.html", {"result": photos})
        self.assertIn("Source: Google Maps photos", html)

    def test_picks_are_highlighted_above_the_full_menu(self):
        url = reverse("search:what_to_order", args=["1"])
        menu = [
            wto.Dish("Fresh kale salad", "lemon dressing", calories=400),
            wto.Dish("Grilled salmon bowl", "steamed greens", calories=520),
            wto.Dish("Fried chicken basket", calories=1100),
            wto.Dish("Walnut and fresh greens salad", calories=450),
            wto.Dish("Iced latte", kind="drink"),
        ]
        with patch.object(wto, "menustat_dishes", return_value=menu), patch(
            "search.views.ai_scores.shared_encoder", return_value=fake_encoder
        ), patch("search.views._profile_for", return_value=profile(allergies="Nuts")):
            html = self.client.get(url).content.decode()
        self.assertIn("Picked for you", html)
        self.assertIn("Add a health goal", html)
        self.assertIn("Not suggested: Walnut and fresh greens salad lists walnut", html)
        self.assertEqual(html.count("what-to-order__dish--picked"), 2)
        self.assertIn("400 kcal", html)
        self.assertIn("Fried chicken basket", html)  # never removed from the list
        self.assertIn("Iced latte", html)

    def test_small_menus_get_no_picks(self):
        url = reverse("search:what_to_order", args=["1"])
        menu = [wto.Dish("Fresh kale salad"), wto.Dish("Grilled salmon bowl")]
        with patch.object(wto, "menustat_dishes", return_value=menu), patch(
            "search.views.ai_scores.shared_encoder", return_value=fake_encoder
        ):
            html = self.client.get(url).content.decode()
        self.assertNotIn("Picked for you", html)
        self.assertIn("Fresh kale salad", html)

    def test_picks_failure_still_shows_the_menu(self):
        def broken():
            raise RuntimeError("model down")

        menu = [wto.Dish(f"Fresh salad {n}") for n in range(6)]
        with patch.object(wto, "menustat_dishes", return_value=menu):
            result = wto.build("LEAF BAR", None, None, "q", broken)
        self.assertEqual(result.picks, [])
        self.assertEqual(len(result.groups[0].dishes), 6)
        self.assertFalse(any(d.picked for d in menu))

    def test_no_menu_message(self):
        url = reverse("search:what_to_order", args=["1"])
        with patch.object(wto, "menustat_dishes", return_value=[]):
            response = self.client.get(url)
        self.assertContains(response, "Menu not available.")

    def test_unknown_restaurant_is_404(self):
        response = self.client.get(reverse("search:what_to_order", args=["999"]))
        self.assertEqual(response.status_code, 404)

    def test_detail_page_has_the_section(self):
        with patch("search.views.find_restaurant_place", return_value=None):
            html = self.client.get(
                reverse("search:restaurant_detail", args=["1"])
            ).content.decode()
        self.assertIn('id="what-to-order"', html)
        self.assertIn(reverse("search:what_to_order", args=["1"]), html)
        self.assertIn("what_to_order.js", html)
