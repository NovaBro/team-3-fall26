"""Load the raw NYC Open Data CSV/JSON files in database/datasets/ into SQLite.

Usage:
    python manage.py import_datasets

The command is idempotent: each target table is cleared before it is reloaded.
"""

import math
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from search.models import (
    FarmersMarket,
    HealthyStore,
    MenuItem,
    RestaurantInspection,
    RestaurantSummary,
)
from search import signals as summary_signals
from search.summary import rebuild_all

DATASETS_DIR = Path(settings.BASE_DIR) / "database" / "datasets"


def _is_na(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


def _text(value):
    if _is_na(value):
        return ""
    return str(value).strip()


def _zipcode(value):
    text = _text(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _number(value):
    text = _text(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int(value):
    number = _number(value)
    return int(number) if number is not None else None


def _bool(value):
    try:
        return bool(int(float(_text(value))))
    except (TypeError, ValueError):
        return False


def _date(value):
    parsed = pd.to_datetime(_text(value), errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


class Command(BaseCommand):
    help = "Import the raw NYC food datasets into the SQLite database."

    def handle(self, *args, **options):
        if str(connection.settings_dict["NAME"]) == str(settings.LITE_DB_PATH):
            raise CommandError(
                "The site is using the lite DB. Import into the full DB with "
                "NYCFOOD_FULL_DATA=1, then run build_lite_db --force."
            )
        if not DATASETS_DIR.exists():
            self.stderr.write(f"Datasets directory not found: {DATASETS_DIR}")
            return

        importers = [
            ("restaurant inspections", RestaurantInspection, self._import_restaurants),
            ("menu items", MenuItem, self._import_menu_items),
            ("farmers markets", FarmersMarket, self._import_markets),
            ("healthy stores", HealthyStore, self._import_stores),
        ]

        with summary_signals.paused():
            for label, model, importer in importers:
                model.objects.all().delete()
                count = importer()
                self.stdout.write(self.style.SUCCESS(f"Imported {count:,} {label}"))
        count = rebuild_all(RestaurantInspection, RestaurantSummary)
        self.stdout.write(self.style.SUCCESS(f"Summarised {count:,} restaurants"))

    def _find(self, pattern):
        matches = sorted(DATASETS_DIR.glob(pattern))
        if not matches:
            raise FileNotFoundError(f"No dataset matching {pattern} in {DATASETS_DIR}")
        return matches[-1]

    def _read_csv(self, pattern):
        df = pd.read_csv(self._find(pattern), low_memory=False)
        df.columns = [" ".join(str(c).split()) for c in df.columns]
        return df.to_dict("records")

    def _bulk(self, model, records):
        with transaction.atomic():
            model.objects.bulk_create(records, batch_size=2000)
        return len(records)

    def _import_restaurants(self):
        # Cuisine comes from a separate CAMIS -> cuisine lookup file.
        lookup = pd.read_csv(self._find("restaurant_cuisines_*.csv"), dtype=str)
        cuisines = {
            _text(camis): _text(cuisine)
            for camis, cuisine in zip(lookup["camis"], lookup["cuisine_description"])
        }
        records = [
            RestaurantInspection(
                camis=_text(row["CAMIS"]),
                dba=_text(row["DBA"]),
                boro=_text(row["BORO"]),
                street=_text(row["STREET"]),
                zipcode=_zipcode(row["ZIPCODE"]),
                cuisine=cuisines.get(_text(row["CAMIS"]), ""),
                inspection_date=_date(row["INSPECTION DATE"]),
                violation_code=_text(row["VIOLATION CODE"]),
                violation_description=_text(row["VIOLATION DESCRIPTION"]),
                grade=_text(row["GRADE"]),
            )
            for row in self._read_csv("restaurant_data_set_2_*.csv")
        ]
        return self._bulk(RestaurantInspection, records)

    def _import_menu_items(self):
        records = [
            MenuItem(
                menu_item_id=_text(row["Menu_Item_ID"]),
                year=_int(row["Year"]),
                restaurant_item_name=_text(row["Restaurant_Item_Name"])[:255],
                restaurant=_text(row["restaurant"])[:255],
                restaurant_id=_text(row["Restaurant_ID"]),
                item_name=_text(row["Item_Name"])[:255],
                item_description=_text(row["Item_Description"]),
                food_category=_text(row["Food_Category"])[:100],
                serving_size=_text(row["Serving_Size"])[:64],
                calories=_number(row["Calories"]),
                total_fat=_number(row["Total_Fat"]),
                saturated_fat=_number(row["Saturated_Fat"]),
                trans_fat=_number(row["Trans_Fat"]),
                cholesterol=_number(row["Cholesterol"]),
                sodium=_number(row["Sodium"]),
                potassium=_number(row["Potassium"]),
                carbohydrates=_number(row["Carbohydrates"]),
                protein=_number(row["Protein"]),
                sugar=_number(row["Sugar"]),
                dietary_fiber=_number(row["Dietary_Fiber"]),
                calories_100g=_number(row["Calories_100g"]),
                kids_meal=_bool(row["Kids_Meal"]),
                limited_time_offer=_bool(row["Limited_Time_Offer"]),
                regional=_bool(row["Regional"]),
                shareable=_bool(row["Shareable"]),
            )
            for row in self._read_csv("DOHMH_MenuStat*.csv")
        ]
        return self._bulk(MenuItem, records)

    def _import_markets(self):
        records = [
            FarmersMarket(
                year=_int(row["Year"]),
                market_name=_text(row["Market Name"]),
                borough=_text(row["Borough"]),
                street_address=_text(row["Street Address"]),
                community_district=_text(row["Community District"]),
                latitude=_number(row["Latitude"]),
                longitude=_number(row["Longitude"]),
                days_of_operation=_text(row["Days of Operation"]),
                hours_of_operations=_text(row["Hours of Operations"]),
                season_dates=_text(row["Season Dates"]),
                accepts_ebt=_text(row["Accepts EBT"]),
                open_year_round=_text(row["Open Year-Round"]),
                stellar_cooking_demonstrations=_text(
                    row["Stellar Cooking Demonstrations"]
                ),
            )
            for row in self._read_csv("NYC_Farmers_Markets_*.csv")
        ]
        return self._bulk(FarmersMarket, records)

    def _import_stores(self):
        records = [
            HealthyStore(
                store_name=_text(row["Store Name"]),
                street_address=_text(row["Street Address"]),
                borough=_text(row["Borough"]),
                zip_code=_zipcode(row["Zip Code"]),
                year_awarded=_int(row["Year Awarded"]),
                program_wave=_text(row["Program Wave"]),
                latitude=_number(row["Latitude"]),
                longitude=_number(row["Longitude"]),
                community_board=_text(row["Community Board"]),
                council_district=_text(row["Council District"]),
                bin=_text(row["BIN"]),
                bbl=_text(row["BBL"]),
                census_tract=_text(row["Census Tract (2020)"]),
                nta=_text(row["Neighborhood Tabulation Area (NTA) (2020)"]),
            )
            for row in self._read_csv("Recognized_Shop_Healthy_Stores_*.csv")
        ]
        return self._bulk(HealthyStore, records)
