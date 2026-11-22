"""import_datasets keeps only the latest market season and fixes store boroughs."""

import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from django.core.management import call_command
from django.db import connections
from django.test import TestCase

from nycfood.test_utils import ALL_DATABASES
from search.models import FarmersMarket, HealthyStore, MenuItem

MENU_COLUMNS = [
    "Menu_Item_ID",
    "Year",
    "Restaurant_Item_Name",
    "restaurant",
    "Restaurant_ID",
    "Item_Name",
    "Item_Description",
    "Food_Category",
    "Serving_Size",
    "Calories",
    "Total_Fat",
    "Saturated_Fat",
    "Trans_Fat",
    "Cholesterol",
    "Sodium",
    "Potassium",
    "Carbohydrates",
    "Protein",
    "Sugar",
    "Dietary_Fiber",
    "Calories_100g",
    "Kids_Meal",
    "Limited_Time_Offer",
    "Regional",
    "Shareable",
]
MARKET_COLUMNS = [
    "Year",
    "Market Name",
    "Borough",
    "Street Address",
    "Community District",
    "Latitude",
    "Longitude",
    "Days of Operation",
    "Hours of Operations",
    "Season Dates",
    "Accepts EBT",
    "Open Year-Round",
    "Stellar Cooking Demonstrations",
]
STORE_COLUMNS = [
    "Store Name",
    "Street Address",
    "Borough",
    "Zip Code",
    "Year Awarded",
    "Program Wave",
    "Latitude",
    "Longitude",
    "Community Board",
    "Council District",
    "BIN",
    "BBL",
    "Census Tract (2020)",
    "Neighborhood Tabulation Area (NTA) (2020)",
]


def _write(directory, name, columns, rows):
    frame = pd.DataFrame([{c: row.get(c, "") for c in columns} for row in rows])
    frame.to_csv(Path(directory) / name, index=False)


class ImportDatasetsTests(TestCase):
    databases = ALL_DATABASES

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        _write(
            self.tmp.name,
            "DOHMH_MenuStat_(Historical)_20261011.csv",
            MENU_COLUMNS,
            [{"Menu_Item_ID": "1", "Year": 2022, "restaurant": "Chain"}],
        )
        _write(
            self.tmp.name,
            "NYC_Farmers_Markets_20261011.csv",
            MARKET_COLUMNS,
            [
                {"Year": 2025, "Market Name": "Old Market", "Borough": "Bronx"},
                {"Year": 2026, "Market Name": "New Market", "Borough": "Bronx"},
                {"Year": 2026, "Market Name": "Other Market", "Borough": "Queens"},
            ],
        )
        _write(
            self.tmp.name,
            "Recognized_Shop_Healthy_Stores_20261011.csv",
            STORE_COLUMNS,
            [
                {"Store Name": "A", "Borough": "New York", "Zip Code": 10029},
                {"Store Name": "B", "Borough": "Bronx", "Zip Code": 10451},
            ],
        )
        patcher = patch(
            "search.management.commands.import_datasets.DATASETS_DIR",
            Path(self.tmp.name),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_keeps_only_latest_market_year(self):
        call_command("import_datasets", stdout=StringIO())
        self.assertEqual(
            sorted(FarmersMarket.objects.values_list("market_name", flat=True)),
            ["New Market", "Other Market"],
        )
        self.assertEqual(
            set(FarmersMarket.objects.values_list("year", flat=True)), {2026}
        )

    def test_new_york_borough_stored_as_manhattan(self):
        call_command("import_datasets", stdout=StringIO())
        self.assertEqual(
            dict(HealthyStore.objects.values_list("store_name", "borough")),
            {"A": "Manhattan", "B": "Bronx"},
        )
        self.assertEqual(MenuItem.objects.count(), 1)

    def test_analyzes_every_database(self):
        out = StringIO()
        call_command("import_datasets", stdout=out)
        self.assertIn("Analyzed", out.getvalue())
        for alias in ALL_DATABASES:
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM sqlite_master WHERE name = 'sqlite_stat1'"
                )
                self.assertEqual(cursor.fetchone()[0], 1, alias)
