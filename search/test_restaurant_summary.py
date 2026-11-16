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


class SummaryBatchTests(TestCase):
    def test_rebuild_in_batches_and_empty_refresh(self):
        from unittest.mock import patch

        from search import summary

        for n in range(3):
            add(str(10 + n), "2026-01-01", "A")
        with patch.object(summary, "BATCH", 2):
            total = summary.rebuild_all(RestaurantInspection, RestaurantSummary)
        self.assertEqual(total, 3)
        self.assertEqual(RestaurantSummary.objects.count(), 3)
        summary.refresh(RestaurantInspection, RestaurantSummary, [None, ""])
        self.assertEqual(RestaurantSummary.objects.count(), 3)


class ImportDatasetsTests(TestCase):
    """import_datasets loads inspections, then builds the summary once."""

    def test_import_builds_summary(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from search.management.commands import import_datasets as cmd

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "restaurant_cuisines_1.csv").write_text(
                "camis,cuisine_description\n50001,Salads\n"
            )
            (folder / "restaurant_data_set_2_1.csv").write_text(
                "CAMIS,DBA,BORO,STREET,ZIPCODE,INSPECTION DATE,"
                "VIOLATION CODE,VIOLATION DESCRIPTION,GRADE\n"
                "50001,GREEN BOWL,Queens,1 Main St,11101.0,01/02/2026,,,A\n"
                "50001,GREEN BOWL,Queens,1 Main St,11101.0,03/04/2025,,,B\n"
            )
            others = [
                "_import_menu_items",
                "_import_purchases",
                "_import_markets",
                "_import_stores",
                "_import_eateries",
            ]
            out = StringIO()
            with patch.object(cmd, "DATASETS_DIR", folder):
                with patch.multiple(
                    cmd.Command, **{name: lambda self: 0 for name in others}
                ):
                    call_command("import_datasets", stdout=out)
        self.assertEqual(RestaurantInspection.objects.count(), 2)
        row = RestaurantSummary.objects.get(camis="50001")
        self.assertEqual((row.latest_grade, row.zipcode), ("A", "11101"))
        self.assertIn("Summarised 1 restaurants", out.getvalue())

    def test_missing_folder_is_reported(self):
        from pathlib import Path
        from unittest.mock import patch

        from search.management.commands import import_datasets as cmd

        err = StringIO()
        with patch.object(cmd, "DATASETS_DIR", Path("/no/such/folder")):
            call_command("import_datasets", stderr=err)
        self.assertIn("not found", err.getvalue())
