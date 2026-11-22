"""The home page works even when RestaurantSummary is missing or empty.

GOOGLE_MAPS_JS_KEY=dummy python manage.py test search.test_summary_fallback
"""

from datetime import date
from unittest import skipIf
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from search import signals, summary_status, views
from search.models import RestaurantInspection, RestaurantSummary

TODAY = date(2026, 11, 15)


def inspection(camis, dba, cuisine, day="2026-06-01", grade="A"):
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


def drop_summary_table():
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE {RestaurantSummary._meta.db_table}")


def explore_names():
    from types import SimpleNamespace

    from django.test import RequestFactory

    request = RequestFactory().get("/")
    request.user = SimpleNamespace(is_authenticated=False, pk=None)
    with patch("search.views._profile_for", return_value=None):
        return [row["name"] for row in views._explore_rows(request)]


@patch("search.views._today", return_value=TODAY)
class SummaryFallbackTests(TestCase):
    databases = {"default", "community"}

    def setUp(self):
        summary_status.reset()
        self.addCleanup(summary_status.reset)
        inspection("1", "OLD SALAD", "Salads", day="2024-01-10")
        inspection("2", "BUSY DINER", "American")
        inspection("3", "GREEN BOWL", "Salads")
        inspection("4", "NEW SPOT", "American", day="1900-01-01", grade="")

    def home(self):
        with patch("search.views.find_restaurant_place", return_value=None):
            return self.client.get(reverse("search:home"))

    def test_group_by_gives_the_same_order_as_the_summary(self, _today):
        with_summary = explore_names()
        summary_status.reset()
        RestaurantSummary.objects.all().delete()
        self.assertFalse(summary_status.summary_ready())
        self.assertEqual(explore_names(), with_summary)

    def test_missing_table_home_still_works(self, _today):
        drop_summary_table()
        self.assertEqual(summary_status.table_status(), summary_status.MISSING)
        response = self.home()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "BUSY DINER")
        response = self.client.get(reverse("search:home") + "?page=2")
        self.assertEqual(response.status_code, 200)

    def test_empty_table_home_still_works(self, _today):
        RestaurantSummary.objects.all().delete()
        self.assertEqual(summary_status.table_status(), summary_status.EMPTY)
        self.assertEqual(self.home().status_code, 200)

    def test_ready_is_remembered(self, _today):
        self.assertTrue(summary_status.summary_ready())
        with patch.object(summary_status, "table_status") as status:
            self.assertTrue(summary_status.summary_ready())
        status.assert_not_called()

    def test_not_ready_is_rechecked_only_after_a_while(self, _today):
        RestaurantSummary.objects.all().delete()
        self.assertFalse(summary_status.summary_ready())
        with patch.object(summary_status, "table_status") as status:
            self.assertFalse(summary_status.summary_ready())
        status.assert_not_called()


class SummaryRepairTests(TestCase):
    def setUp(self):
        summary_status.reset()
        self.addCleanup(summary_status.reset)
        with signals.paused():
            inspection("7", "GREEN BOWL", "Salads")

    def test_repair_fills_an_empty_table(self):
        self.assertEqual(summary_status.table_status(), summary_status.EMPTY)
        with patch.object(summary_status.connections["default"], "close"):
            summary_status.repair()
        self.assertTrue(RestaurantSummary.objects.filter(camis="7").exists())
        self.assertEqual(summary_status.table_status(), summary_status.READY)

    def test_repair_runs_migrate_when_the_table_is_missing(self):
        calls = []

        def fake_migrate(*args, **kwargs):
            calls.append(args)

        with patch.object(
            summary_status, "table_status", side_effect=["missing", "empty", "ready"]
        ), patch.object(summary_status, "call_command", fake_migrate), patch(
            "search.summary.rebuild_all", return_value=1
        ) as rebuild, patch.object(
            summary_status.connections["default"], "close"
        ):
            summary_status.repair()
        self.assertEqual(calls, [("migrate", "search")])
        rebuild.assert_called_once()

    @skipIf(summary_status.fcntl is None, "fcntl is not available on Windows")
    def test_only_one_process_repairs(self):
        fcntl = summary_status.fcntl

        with open(summary_status.LOCK_PATH, "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # flock locks belong to the open file, so a second open is refused
            with patch.object(summary_status, "table_status") as status, patch.object(
                summary_status.connections["default"], "close"
            ):
                summary_status.repair()
            status.assert_not_called()

    def test_repair_runs_without_fcntl(self):
        # Windows has no fcntl: repair still works, just without the lock
        with patch.object(summary_status, "fcntl", None), patch.object(
            summary_status, "table_status", side_effect=["empty", "ready"]
        ), patch("search.summary.rebuild_all", return_value=1) as rebuild, patch.object(
            summary_status.connections["default"], "close"
        ):
            summary_status.repair()
        rebuild.assert_called_once()

    def test_repair_errors_are_logged_not_raised(self):
        with patch.object(
            summary_status, "table_status", side_effect=RuntimeError("boom")
        ), patch.object(summary_status.connections["default"], "close"):
            with self.assertLogs("search.summary_status", "ERROR"):
                summary_status.repair()

    @override_settings(RESTAURANT_SUMMARY_SELF_REPAIR=True)
    def test_not_ready_starts_one_background_repair(self):
        with patch.object(summary_status.threading, "Thread") as thread:
            self.assertFalse(summary_status.summary_ready())
            summary_status._state["checked_at"] = None
            self.assertFalse(summary_status.summary_ready())  # still repairing
        thread.assert_called_once()
        thread.return_value.start.assert_called_once()
