"""Tests for build_lite_db: quotas, ranking, and the copy-and-prune command."""

import io
import sqlite3
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from community.keys import dohmh_key, farmers_market_key, grocery_key
from search.management.commands.build_lite_db import (
    bayes_score,
    borough_quotas,
    pick_ranked,
    pick_restaurants,
)


def row(camis, boro="Manhattan", grade="A", last_date="2025-01-01"):
    return {"camis": camis, "boro": boro, "latest_grade": grade, "last_date": last_date}


class QuotaTests(SimpleTestCase):
    def test_total_equals_limit_and_floor_applies(self):
        counts = {"Manhattan": 12000, "Brooklyn": 8000, "Staten Island": 1100}
        quotas = borough_quotas(counts, 100, minimum=20)
        self.assertEqual(sum(quotas.values()), 100)
        self.assertGreaterEqual(quotas["Staten Island"], 20)
        self.assertGreater(quotas["Manhattan"], quotas["Brooklyn"])

    def test_quota_never_exceeds_candidates(self):
        quotas = borough_quotas({"Bronx": 3, "Queens": 1000}, 50, minimum=10)
        self.assertEqual(quotas, {"Bronx": 3, "Queens": 47})

    def test_floor_shrinks_when_limit_is_small(self):
        quotas = borough_quotas({"A": 100, "B": 100, "C": 100}, 6, minimum=40)
        self.assertEqual(quotas, {"A": 2, "B": 2, "C": 2})


class ScoreTests(SimpleTestCase):
    def test_many_reviews_beat_few_perfect_ones(self):
        self.assertGreater(bayes_score(4.5, 2000, 4.0), bayes_score(5.0, 3, 4.0))

    def test_no_data_is_none(self):
        self.assertIsNone(bayes_score(None, 10, 4.0))
        self.assertIsNone(bayes_score(4.5, 0, 4.0))


class PickTests(SimpleTestCase):
    def test_restaurants_ranked_spread_and_filtered(self):
        rows = [
            row("1"),
            row("2"),
            row("3"),
            row("4", grade="C"),
            row("5"),
            row("6", boro="Bronx"),
            row("7", boro="0"),
        ]
        enrichment = {
            dohmh_key("1"): (4.8, 900, "OPERATIONAL"),
            dohmh_key("2"): (4.9, 2, "OPERATIONAL"),
            dohmh_key("3"): (5.0, 999, "CLOSED_PERMANENTLY"),
            dohmh_key("4"): (5.0, 999, "OPERATIONAL"),
        }
        kept = pick_restaurants(rows, enrichment, limit=3, minimum=1)
        # Bronx gets its floor; Manhattan's best by score, closed/C/unknown boro out.
        self.assertCountEqual(kept, ["1", "2", "6"])

    def test_restaurants_without_google_data_backfill_grade_a_first(self):
        rows = [row("1", grade="B"), row("2", grade="A"), row("3")]
        enrichment = {dohmh_key("3"): (3.0, 10, "OPERATIONAL")}
        kept = pick_restaurants(rows, enrichment, limit=2, minimum=1)
        self.assertEqual(kept, ["3", "2"])

    def test_pick_ranked(self):
        enrichment = {
            "a": (4.0, 100, "OPERATIONAL"),
            "b": (4.7, 300, "OPERATIONAL"),
            "c": (5.0, 500, "CLOSED_TEMPORARILY"),
        }
        items = [(1, "a"), (2, "b"), (3, "c"), (4, "unrated")]
        self.assertEqual(pick_ranked(items, enrichment, 3), [2, 1, 4])


class CommandTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.full = str(folder / "full.db")
        self.community = str(folder / "community.db")
        self.lite = str(folder / "lite.db")

        db = sqlite3.connect(self.full)
        db.executescript("""
            CREATE TABLE search_restaurantsummary (camis TEXT PRIMARY KEY,
                boro TEXT, latest_grade TEXT, last_date TEXT);
            CREATE TABLE search_restaurantinspection (id INTEGER PRIMARY KEY,
                camis TEXT);
            CREATE TABLE search_healthystore (id INTEGER PRIMARY KEY,
                store_name TEXT, street_address TEXT, zip_code TEXT);
            CREATE TABLE search_farmersmarket (id INTEGER PRIMARY KEY, year INTEGER,
                market_name TEXT, street_address TEXT);
            CREATE TABLE search_menuitem (id INTEGER PRIMARY KEY);
            INSERT INTO search_restaurantsummary VALUES
                ('1', 'Manhattan', 'A', '2025-01-01'),
                ('2', 'Manhattan', 'A', '2025-01-01'),
                ('3', 'Manhattan', 'A', '2025-01-01');
            INSERT INTO search_restaurantinspection (camis)
                VALUES ('1'), ('1'), ('2'), ('3');
            INSERT INTO search_healthystore VALUES
                (1, 'Good Store', '1 Main St', '10001'),
                (2, 'Ok Store', '2 Main St', '10001');
            INSERT INTO search_farmersmarket VALUES
                (1, 2026, 'Union Sq', 'E 17th St'),
                (2, 2026, 'Tiny', 'Elm St');
            INSERT INTO search_menuitem VALUES (1), (2);
            """)
        db.commit()
        db.close()

        db = sqlite3.connect(self.community)
        db.execute(
            "CREATE TABLE community_placeenrichment (kind TEXT, key TEXT, "
            "rating REAL, user_rating_count INTEGER, business_status TEXT)"
        )
        db.executemany(
            "INSERT INTO community_placeenrichment VALUES (?, ?, ?, ?, ?)",
            [
                ("restaurant_dohmh", dohmh_key("1"), 4.8, 900, "OPERATIONAL"),
                ("restaurant_dohmh", dohmh_key("3"), 4.5, 400, "OPERATIONAL"),
                (
                    "grocery",
                    grocery_key("Good Store", "1 Main St", "10001"),
                    4.6,
                    200,
                    "OPERATIONAL",
                ),
                (
                    "farmers_market",
                    farmers_market_key(2026, "Union Sq", "E 17th St"),
                    4.8,
                    5000,
                    "OPERATIONAL",
                ),
            ],
        )
        db.commit()
        db.close()

    def run_command(self, **extra):
        call_command(
            "build_lite_db",
            limit=1,
            source=self.full,
            community=self.community,
            dest=self.lite,
            stdout=io.StringIO(),
            **extra,
        )

    def ids(self, path, sql):
        db = sqlite3.connect(path)
        try:
            return sorted(r[0] for r in db.execute(sql))
        finally:
            db.close()

    def test_builds_pruned_copy_and_leaves_source_alone(self):
        with open(self.full, "rb") as handle:
            before = handle.read()
        self.run_command()
        with open(self.full, "rb") as handle:
            self.assertEqual(handle.read(), before)

        q = self.ids
        self.assertEqual(
            q(self.lite, "SELECT camis FROM search_restaurantsummary"), ["1"]
        )
        self.assertEqual(
            q(self.lite, "SELECT camis FROM search_restaurantinspection"), ["1", "1"]
        )
        self.assertEqual(q(self.lite, "SELECT id FROM search_healthystore"), [1])
        self.assertEqual(q(self.lite, "SELECT id FROM search_farmersmarket"), [1])
        self.assertEqual(q(self.lite, "SELECT id FROM search_menuitem"), [1, 2])

    def test_refuses_to_overwrite_without_force(self):
        self.run_command()
        with self.assertRaises(CommandError):
            self.run_command()
        self.run_command(force=True)

    def test_refuses_same_source_and_dest(self):
        with self.assertRaises(CommandError):
            call_command(
                "build_lite_db",
                source=self.full,
                community=self.community,
                dest=self.full,
                stdout=io.StringIO(),
            )


class ImportGuardTests(SimpleTestCase):
    databases = {"default"}

    def test_import_datasets_refuses_the_lite_db(self):
        from unittest import mock

        from django.db import connection

        with mock.patch.dict(connection.settings_dict, {"NAME": "/x/lite.db"}):
            with self.settings(LITE_DB_PATH="/x/lite.db"):
                with self.assertRaises(CommandError):
                    call_command("import_datasets", stdout=io.StringIO())
