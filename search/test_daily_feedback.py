"""Daily rotation, cuisine diversity, and Like / Not interested feedback."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import UserProfile
from community.keys import DOHMH, dohmh_key
from community.models import CommunitySubject, RecommendationFeedback, UserRating
from search import views
from search.models import RestaurantInspection
from search.recommend import (
    FeedbackPrefs,
    build_feedback_prefs,
    daily_sample,
    daily_seed,
    feedback_adjustment,
    pick_top,
    score_restaurant,
)


def item(name, score, cuisine, like_bonus=0.0):
    return {"name": name, "score": score, "cuisine": cuisine, "like_bonus": like_bonus}


class DailySampleTests(SimpleTestCase):
    rows = [{"camis": str(n)} for n in range(50)]

    def test_same_seed_same_picks(self):
        seed = daily_seed(date(2026, 11, 8), 7)
        self.assertEqual(
            daily_sample(self.rows, 9, seed), daily_sample(self.rows, 9, seed)
        )

    def test_new_day_new_picks(self):
        monday = daily_sample(self.rows, 9, daily_seed(date(2026, 11, 9), 7))
        tuesday = daily_sample(self.rows, 9, daily_seed(date(2026, 11, 10), 7))
        self.assertEqual(len(monday), 9)
        self.assertNotEqual(monday, tuesday)

    def test_anonymous_seed_and_small_pools(self):
        self.assertEqual(daily_seed(date(2026, 11, 8)), "2026-11-08:0")
        self.assertEqual(daily_sample(self.rows[:3], 9, "x"), self.rows[:3])

    def test_sample_keeps_original_order(self):
        picked = daily_sample(self.rows, 9, "seed")
        self.assertEqual(picked, sorted(picked, key=lambda row: int(row["camis"])))


class PickTopTests(SimpleTestCase):
    def test_skips_repeated_cuisine(self):
        chosen = pick_top(
            [
                item("Green Bowl", 90, "Salads"),
                item("Leaf & Co", 88, "Salads"),
                item("Poke Place", 80, "Hawaiian"),
                item("Taqueria", 70, "Mexican"),
            ]
        )
        names = [i["name"] for i in chosen]
        self.assertEqual(names, ["Green Bowl", "Poke Place", "Taqueria"])

    def test_refills_from_skipped_when_short(self):
        chosen = pick_top(
            [item("A", 90, "Salads"), item("B", 80, "Salads"), item("C", 70, "Thai")]
        )
        self.assertEqual([i["name"] for i in chosen], ["A", "C", "B"])

    def test_blank_cuisines_are_not_merged(self):
        chosen = pick_top([item("A", 3, ""), item("B", 2, ""), item("C", 1, "")])
        self.assertEqual(len(chosen), 3)

    def test_only_one_pick_uses_its_like_bonus(self):
        chosen = pick_top(
            [
                item("Liked Mex", 95, "Mexican", like_bonus=9),  # 86 without bonus
                item("Liked Thai", 94, "Thai", like_bonus=9),  # 85 without bonus
                item("Salad", 88, "Salads"),
                item("Poke", 87, "Hawaiian"),
            ]
        )
        self.assertEqual([i["name"] for i in chosen], ["Liked Mex", "Salad", "Poke"])


class FeedbackPrefsTests(SimpleTestCase):
    def test_buttons_and_stars(self):
        prefs = build_feedback_prefs(
            explicit=[("1", "TAQUERIA", "Mexican", 1), ("2", "BURGER", "Burgers", -1)],
            star_ratings=[
                ("3", "PHO", "Vietnamese", 5),
                ("4", "PIZZA", "Pizza", 1),
                ("5", "DINER", "American", 3),
            ],
        )
        self.assertEqual(
            prefs.liked,
            {"Mexican": [("1", "TAQUERIA")], "Vietnamese": [("3", "PHO")]},
        )
        self.assertEqual(prefs.hidden, {"2", "4"})
        self.assertEqual(prefs.not_interested, {"Burgers": 1, "Pizza": 1})

    def test_button_wins_over_star_rating(self):
        prefs = build_feedback_prefs(
            explicit=[("1", "TAQUERIA", "Mexican", -1)],
            star_ratings=[("1", "TAQUERIA", "Mexican", 5)],
        )
        self.assertEqual(prefs.liked, {})
        self.assertEqual(prefs.hidden, {"1"})

    def test_like_bonus_is_capped(self):
        liked = [("1", "TAQUERIA"), ("2", "B"), ("3", "C"), ("4", "D")]
        prefs = FeedbackPrefs(liked={"Mexican": liked})
        bonus, penalty, tag = feedback_adjustment("Mexican", prefs, "99")
        self.assertEqual(
            (bonus, penalty, tag), (9.0, 0.0, "Because you liked Taqueria")
        )
        self.assertEqual(feedback_adjustment("Thai", prefs, "99"), (0.0, 0.0, None))

    def test_own_like_does_not_boost_itself(self):
        prefs = FeedbackPrefs(liked={"Mexican": [("1", "TAQUERIA")]})
        self.assertEqual(
            feedback_adjustment("Mexican", prefs, "1"), (0.0, 0.0, "You liked this")
        )

    def test_cuisine_penalty_after_two_not_interested(self):
        once = FeedbackPrefs(not_interested={"Pizza": 1})
        twice = FeedbackPrefs(not_interested={"Pizza": 2})
        self.assertEqual(feedback_adjustment("Pizza", once)[1], 0.0)
        self.assertEqual(feedback_adjustment("Pizza", twice)[1], -5.0)

    def test_score_shows_feedback_in_breakdown_and_tags(self):
        prefs = FeedbackPrefs(liked={"Mexican": [("1", "TAQUERIA")]})
        base, _tags, _ = score_restaurant(name="X", cuisine="Mexican", grade="A")
        score, tags, breakdown = score_restaurant(
            name="X", cuisine="Mexican", grade="A", feedback=prefs
        )
        self.assertEqual(score - base, 3.0)
        self.assertEqual(tags[0], "Because you liked Taqueria")
        self.assertEqual(breakdown["like_bonus"], 3.0)
        self.assertIn(
            {"label": "Similar to places you liked", "delta": 3.0},
            breakdown["adjustments"],
        )


@patch("search.views.find_restaurant_place", return_value=None)
class FeedbackViewTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        rows = [
            ("1", "GREEN LEAF", "Salads", "2024-07-04"),
            ("2", "LEAF AND CO", "Salads", "2024-07-03"),
            ("3", "TAQUERIA", "Mexican", "2024-07-02"),
            ("4", "THAI SPOT", "Thai", "2024-07-01"),
        ]
        for camis, dba, cuisine, day in rows:
            RestaurantInspection.objects.create(
                camis=camis,
                dba=dba,
                boro="Queens",
                street="1 Main St",
                zipcode="11101",
                cuisine=cuisine,
                inspection_date=day,
                grade="A",
            )
        self.user = User.objects.create_user("sam", "sam@example.com", "pw-12345!")

    def picks(self):
        response = self.client.get(reverse("search:home"))
        return response, [p["name"] for p in response.context["top_picks"]]

    def press(self, camis, value):
        return self.client.post(
            reverse("search:pick_feedback", args=[camis]), {"value": value}
        )

    def test_anonymous_sees_diverse_picks_and_no_buttons(self, _find):
        response, names = self.picks()
        self.assertEqual(len(names), 3)
        self.assertEqual(len({"GREEN LEAF", "LEAF AND CO"} & set(names)), 1)
        self.assertNotContains(response, "top-pick-card__feedback")

    def test_buttons_require_login(self, _find):
        response = self.press("1", "like")
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
        self.assertFalse(RecommendationFeedback.objects.exists())

    def test_like_saves_and_pressing_again_undoes(self, _find):
        self.client.force_login(self.user)
        self.press("3", "like")
        saved = RecommendationFeedback.objects.get()
        self.assertEqual((saved.camis, saved.value), ("3", 1))
        self.assertEqual((saved.name, saved.cuisine), ("TAQUERIA", "Mexican"))
        response, _names = self.picks()
        self.assertContains(response, 'aria-pressed="true"')
        taqueria = next(
            p for p in response.context["top_picks"] if p["name"] == "TAQUERIA"
        )
        self.assertEqual(taqueria["reason_tags"][0], "You liked this")
        self.assertEqual(taqueria["like_bonus"], 0.0)
        self.press("3", "like")
        self.assertFalse(RecommendationFeedback.objects.exists())

    def test_not_interested_hides_the_place(self, _find):
        self.client.force_login(self.user)
        self.press("1", "not_interested")
        _response, names = self.picks()
        self.assertNotIn("GREEN LEAF", names)
        self.assertEqual(len(names), 3)

    def test_like_tags_similar_place(self, _find):
        RestaurantInspection.objects.create(
            camis="9",
            dba="OLD TAQUERIA",
            boro="Queens",
            street="2 Main St",
            zipcode="11101",
            cuisine="Mexican",
            inspection_date="2020-01-01",
            grade="A",
        )
        RecommendationFeedback.objects.create(
            user_id=self.user.pk,
            camis="9",
            name="OLD TAQUERIA",
            cuisine="Mexican",
            value=RecommendationFeedback.LIKE,
        )
        self.client.force_login(self.user)
        response, _names = self.picks()
        taqueria = next(
            p for p in response.context["top_picks"] if p["name"] == "TAQUERIA"
        )
        self.assertEqual(taqueria["reason_tags"][0], "Because you liked Old Taqueria")

    def test_one_star_rating_hides_the_place(self, _find):
        subject = CommunitySubject.objects.create(kind=DOHMH, key=dohmh_key("1"))
        UserRating.objects.create(subject=subject, user_id=self.user.pk, score=1)
        self.client.force_login(self.user)
        _response, names = self.picks()
        self.assertNotIn("GREEN LEAF", names)

    def test_unknown_value_and_restaurant(self, _find):
        self.client.force_login(self.user)
        self.assertEqual(self.press("1", "love").status_code, 302)
        self.assertFalse(RecommendationFeedback.objects.exists())
        self.assertEqual(self.press("404", "like").status_code, 404)

    def test_next_must_be_local(self, _find):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("search:pick_feedback", args=["1"]),
            {"value": "like", "next": "https://evil.example.com/"},
        )
        self.assertEqual(response["Location"], reverse("search:home"))


class DailyPoolTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        for n in range(60):
            RestaurantInspection.objects.create(
                camis=str(1000 + n),
                dba=f"PLACE {n}",
                boro="Queens",
                street="1 Main St",
                zipcode="11101",
                cuisine="American",
                inspection_date=f"2024-{1 + n % 12:02d}-{1 + n % 28:02d}",
                grade="A",
            )

    def pool(self, day):
        seed = daily_seed(day, None)
        return {row["camis"] for row in views._build_candidate_pool(None, None, seed)}

    def test_pool_rotates_daily_and_is_stable_within_a_day(self):
        monday = self.pool(date(2026, 11, 9))
        self.assertEqual(len(monday), views.POOL_SIZE)
        self.assertEqual(monday, self.pool(date(2026, 11, 9)))
        self.assertNotEqual(monday, self.pool(date(2026, 11, 10)))

    def test_hidden_places_never_enter_the_pool(self):
        prefs = FeedbackPrefs(hidden={str(1000 + n) for n in range(55)})
        seed = daily_seed(date(2026, 11, 9), 1)
        pool = {row["camis"] for row in views._build_candidate_pool(None, prefs, seed)}
        self.assertTrue(pool)
        self.assertFalse(pool & prefs.hidden)


def inspection(camis, dba, cuisine, grade, day="2024-07-01"):
    return RestaurantInspection.objects.create(
        camis=camis,
        dba=dba,
        boro="Queens",
        street="1 Main St",
        zipcode="11101",
        cuisine=cuisine,
        inspection_date=day,
        grade=grade,
    )


class ExploreOrderTests(TestCase):
    databases = {"default", "community"}

    def order(self):
        return [row["name"] for row in views._explore_rows()]

    def test_best_first_using_db_data_only(self):
        inspection("10", "MCDONALD'S", "Hamburgers", "A")  # 2 - 1 - 2 = -1
        inspection("11", "GRADE B DINER", "American", "B")  # 1
        inspection("12", "AMERICAN GRILL", "American", "A")  # 2
        inspection("13", "GREEN BOWL", "Salads", "A")  # 3
        inspection("14", "PENDING PIZZA", "Pizza", "")  # -1 + 0
        with patch("search.views.find_restaurant_place") as find:
            names = self.order()
        find.assert_not_called()
        self.assertEqual(names[:3], ["GREEN BOWL", "AMERICAN GRILL", "GRADE B DINER"])
        self.assertEqual(set(names[3:]), {"MCDONALD'S", "PENDING PIZZA"})

    def test_latest_grade_counts(self):
        inspection("20", "WAS GOOD", "American", "A", day="2023-01-01")
        inspection("20", "WAS GOOD", "American", "C", day="2024-01-01")
        inspection("20", "WAS GOOD", "American", "", day="2025-01-01")
        inspection("21", "STILL GOOD", "American", "A", day="2024-01-01")
        rows = {row["name"]: row for row in views._explore_rows()}
        self.assertEqual(rows["WAS GOOD"]["latest_grade"], "C")
        self.assertEqual(self.order(), ["STILL GOOD", "WAS GOOD"])

    def test_ties_shuffle_daily_and_stay_put_within_a_day(self):
        for n in range(30):
            inspection(str(5000 + n), f"PLACE {n:02d}", "American", "A")
        with patch("search.views._today", return_value=date(2026, 11, 9)):
            monday = self.order()
            self.assertEqual(monday, self.order())
        with patch("search.views._today", return_value=date(2026, 11, 10)):
            tuesday = self.order()
        self.assertEqual(sorted(monday), sorted(tuesday))
        self.assertNotEqual(monday, tuesday)
        self.assertNotEqual(monday, sorted(monday))  # not alphabetical

    @patch("search.views.find_restaurant_place", return_value=None)
    def test_first_page_skips_places_already_in_top_picks(self, _find):
        for n in range(5):
            inspection(str(6000 + n), f"SPOT {n}", "American", "A")
        response = self.client.get(reverse("search:home"))
        picked = {pick["camis"] for pick in response.context["top_picks"]}
        listed = {row["camis"] for row in response.context["restaurants"]}
        self.assertEqual(len(picked), 3)
        self.assertFalse(picked & listed)
        self.assertEqual(len(listed), 2)


@patch("search.views.find_restaurant_place", return_value=None)
class BoroughTopPicksTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        cuisines = ["American", "Thai", "Salads", "Mexican"]
        for n, boro in enumerate(["Brooklyn"] * 4 + ["Queens"] * 4):
            RestaurantInspection.objects.create(
                camis=str(7000 + n),
                dba=f"{boro.upper()} SPOT {n}",
                boro=boro,
                street="1 Main St",
                zipcode="11201",
                cuisine=cuisines[n % 4],
                inspection_date="2024-07-01",
                grade="A",
            )

    def test_selected_borough_keeps_top_picks_from_that_borough(self, _find):
        response = self.client.get(reverse("search:home"), {"boro": "Brooklyn"})
        picks = response.context["top_picks"]
        self.assertEqual(len(picks), 3)
        self.assertEqual({pick["boro"] for pick in picks}, {"Brooklyn"})
        self.assertContains(response, "Top Picks in Brooklyn")

    def test_all_boroughs_title_and_mix(self, _find):
        response = self.client.get(reverse("search:home"))
        self.assertEqual(len(response.context["top_picks"]), 3)
        self.assertNotContains(response, "Top Picks in")

    def test_no_top_picks_after_page_one(self, _find):
        for n in range(20):
            RestaurantInspection.objects.create(
                camis=str(8000 + n),
                dba=f"MORE {n}",
                boro="Brooklyn",
                street="1 Main St",
                zipcode="11201",
                cuisine="American",
                inspection_date="2024-07-01",
                grade="A",
            )
        response = self.client.get(
            reverse("search:home"), {"boro": "Brooklyn", "page": 2}
        )
        self.assertEqual(response.context["top_picks"], [])

    def test_home_borough_extras_only_when_it_matches(self, _find):
        user = User.objects.create_user("lee", "lee@example.com", "pw-12345!")
        UserProfile.objects.create(user=user, home_address="Astoria, Queens")
        self.client.force_login(user)
        response = self.client.get(reverse("search:home"), {"boro": "Brooklyn"})
        boros = {pick["boro"] for pick in response.context["top_picks"]}
        self.assertEqual(boros, {"Brooklyn"})


@patch("search.views.find_restaurant_place", return_value=None)
class MealOnlyTopPicksTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        inspection("30", "STARBUCKS", "Coffee/Tea", "A", day="2024-07-09")
        inspection("31", "STARBUCKS #812", "American", "A", day="2024-07-08")
        inspection(
            "32", "MAGNOLIA BAKERY", "Bakery Products/Desserts", "A", "2024-07-07"
        )
        inspection("33", "CARVEL", "Frozen Desserts", "A", day="2024-07-06")
        inspection("34", "GREEN JUICE BAR", "Juice, Smoothies, Fruit Salads", "A")
        inspection("35", "TAQUERIA", "Mexican", "A")
        inspection("36", "AMERICAN GRILL", "American", "A")

    def test_coffee_and_dessert_places_are_not_top_picks(self, _find):
        response = self.client.get(reverse("search:home"))
        names = {pick["name"] for pick in response.context["top_picks"]}
        self.assertEqual(names, {"GREEN JUICE BAR", "TAQUERIA", "AMERICAN GRILL"})

    def test_explore_more_lists_them_lower(self, _find):
        order = [row["name"] for row in views._explore_rows()]
        self.assertEqual(order[0], "GREEN JUICE BAR")  # A + healthy = 3
        self.assertEqual(set(order[1:3]), {"TAQUERIA", "AMERICAN GRILL"})  # 2
        self.assertEqual(
            set(order[3:]),
            {"STARBUCKS", "STARBUCKS #812", "MAGNOLIA BAKERY", "CARVEL"},  # 1
        )


class CuisineLabelTests(SimpleTestCase):
    def test_healthy_cuisines_use_exact_dohmh_labels(self):
        from search.recommend import HEALTHY_CUISINES, health_score

        self.assertIn("Juice, Smoothies, Fruit Salads", HEALTHY_CUISINES)
        self.assertIn("Soups/Salads/Sandwiches", HEALTHY_CUISINES)
        self.assertNotIn("Juice/Smoothies", HEALTHY_CUISINES)
        self.assertEqual(health_score("Juice, Smoothies, Fruit Salads", [], "X"), 0.7)


class DisplayReviewTests(SimpleTestCase):
    def review(self, text, rating=5):
        return {"text": text, "author_name": "A", "rating": rating}

    def test_prefers_the_healthiest_review(self):
        from search.recommend import pick_display_review

        reviews = [
            self.review("Great service, nice staff."),
            self.review("Fresh salad, light and healthy!", rating=4),
            self.review("Fresh bowls."),
            self.review("Healthy but greasy fries and fried chicken."),
        ]
        self.assertIs(pick_display_review(reviews), reviews[1])

    def test_ties_keep_google_order(self):
        from search.recommend import pick_display_review

        reviews = [self.review("ok"), self.review("fresh"), self.review("healthy")]
        self.assertIs(pick_display_review(reviews), reviews[1])

    def test_falls_back_to_the_first_review(self):
        from search.recommend import pick_display_review

        reviews = [self.review(""), self.review("Nice staff."), self.review("Greasy")]
        self.assertIs(pick_display_review(reviews), reviews[1])
        self.assertIsNone(pick_display_review([]))

    def test_only_four_and_five_star_reviews(self):
        from search.recommend import pick_display_review

        reviews = [
            self.review("Fresh, healthy salad but rude staff.", rating=1),
            self.review("Fresh and light.", rating=2),
            self.review("Nice staff.", rating=4),
            self.review("Healthy bowls.", rating=5),
        ]
        self.assertIs(pick_display_review(reviews), reviews[3])
        self.assertIs(pick_display_review(reviews[:3]), reviews[2])
        self.assertIsNone(pick_display_review(reviews[:2]))
        self.assertIsNone(pick_display_review([{"text": "Fresh", "rating": None}]))

    def test_goal_words_count(self):
        from search.recommend import pick_display_review

        reviews = [self.review("Nice place."), self.review("Lots of protein.")]
        profile = SimpleNamespace(health_goals=["muscle-gain"])
        self.assertIs(pick_display_review(reviews), reviews[0])
        self.assertIs(pick_display_review(reviews, profile), reviews[1])


@patch("search.views.find_restaurant_place")
class CardReviewTests(TestCase):
    databases = {"default", "community"}

    def test_card_shows_the_healthy_review(self, find):
        inspection("40", "GREEN LEAF", "Salads", "A")
        find.return_value = {
            "name": "Green Leaf",
            "address": "",
            "rating": 4.5,
            "rating_count": 100,
            "reviews": [
                {"text": "Nice staff.", "author_name": "A", "rating": 5},
                {"text": "So fresh and healthy.", "author_name": "B", "rating": 4},
            ],
            "review": {"text": "Nice staff.", "author_name": "A", "rating": 5},
        }
        response = self.client.get(reverse("search:home"))
        pick = response.context["top_picks"][0]
        self.assertEqual(pick["review"]["text"], "So fresh and healthy.")


class HealthyCandidateTests(TestCase):
    databases = {"default", "community"}

    def pool(self, profile=None, seed="2026-11-10:0:"):
        return [row["name"] for row in views._build_candidate_pool(profile, None, seed)]

    def test_best_db_score_beats_recent_inspection(self):
        for n in range(12):  # inspected recently, plain cuisine
            inspection(str(9000 + n), f"RECENT {n}", "American", "A", day="2026-10-01")
        for n in range(9):  # inspected long ago, healthy cuisine
            inspection(str(9100 + n), f"HEALTHY {n}", "Salads", "A", day="2021-01-01")
        names = self.pool()
        self.assertEqual(len(names), 9)
        self.assertTrue(all(name.startswith("HEALTHY") for name in names))

    def test_latest_grade_must_be_a(self):
        inspection("9200", "FELL TO C", "Salads", "A", day="2023-01-01")
        inspection("9200", "FELL TO C", "Salads", "C", day="2024-01-01")
        inspection("9201", "STILL A", "American", "A", day="2024-01-01")
        self.assertEqual(self.pool(), ["STILL A"])

    def test_home_borough_extras_skip_coffee_shops(self):
        inspection("9300", "TAQUERIA", "Mexican", "A")
        for n in range(5):
            RestaurantInspection.objects.create(
                camis=str(9310 + n),
                dba=f"STARBUCKS #{n}",
                boro="Bronx",
                street="1 Main St",
                zipcode="10453",
                cuisine="American",
                inspection_date="2024-07-01",
                grade="A",
            )
        profile = SimpleNamespace(
            allergies="",
            favorite_foods="",
            home_address="Fordham, Bronx",
        )
        self.assertEqual(self.pool(profile), ["TAQUERIA"])
