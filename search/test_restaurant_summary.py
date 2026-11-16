"""RestaurantSummary: one row per restaurant, kept in step with inspections."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from search import signals
from search.models import RestaurantInspection, RestaurantSummary


def add(camis, day, grade="", dba="CAFE", cuisine="Salads"):
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


class SummaryTests(TestCase):
    def test_latest_graded_inspection_wins(self):
        add("1", "2025-01-01", "B")
        add("1", "2026-01-01", "A")
        add("1", "2026-03-01", "")  # newer but ungraded
        row = RestaurantSummary.objects.get(camis="1")
        self.assertEqual(row.latest_grade, "A")
        self.assertEqual(str(row.last_date), "2026-03-01")

    def test_blank_names_are_left_out(self):
        add("2", "2026-01-01", "A", dba="")
        self.assertFalse(RestaurantSummary.objects.filter(camis="2").exists())

    def test_delete_refreshes_the_row(self):
        add("3", "2025-01-01", "B")
        newest = add("3", "2026-01-01", "A")
        newest.delete()
        self.assertEqual(RestaurantSummary.objects.get(camis="3").latest_grade, "B")
        RestaurantInspection.objects.get(camis="3").delete()
        self.assertFalse(RestaurantSummary.objects.filter(camis="3").exists())

    def test_paused_skips_refresh_and_rebuild_catches_up(self):
        with signals.paused():
            add("4", "2026-01-01", "A")
        self.assertFalse(RestaurantSummary.objects.filter(camis="4").exists())
        out = StringIO()
        call_command("rebuild_restaurant_summary", stdout=out)
        self.assertTrue(RestaurantSummary.objects.filter(camis="4").exists())
        self.assertIn("1 restaurants summarised", out.getvalue())
