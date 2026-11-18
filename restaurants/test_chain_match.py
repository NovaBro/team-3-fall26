"""Matching a Google place to a city inspection record when a chain has
several branches with the same name in one ZIP code."""

from django.test import SimpleTestCase

from restaurants.inspections import _match

BRANCHES = [
    ("1", "JUST SALAD", "3 AVENUE"),
    ("2", "JUST SALAD", "EAST   39 STREET"),
    ("3", "JUST SALAD", "5 AVENUE"),
]


class ChainMatchTests(SimpleTestCase):
    def test_street_picks_the_branch(self):
        address = "295 5th Ave, New York, NY 10016, USA"
        self.assertEqual(_match("Just Salad", address, BRANCHES), "3")

    def test_ambiguous_street_still_gives_up(self):
        address = "1 Park Ave, New York, NY 10016, USA"
        self.assertIsNone(_match("Just Salad", address, BRANCHES))

    def test_single_branch_needs_no_street(self):
        address = "9 Nowhere St, New York, NY 10016, USA"
        self.assertEqual(_match("Just Salad", address, BRANCHES[:1]), "1")
