from django.test import TestCase

from restaurants.inspections import (
    attach_inspections,
    google_street,
    google_zip,
    normalize_name,
)
from search.models import RestaurantInspection


def inspect(camis, dba, street, zipcode, grade="A"):
    return RestaurantInspection.objects.create(
        camis=camis,
        dba=dba,
        boro="Manhattan",
        street=street,
        zipcode=zipcode,
        grade=grade,
    )


def place(name, address, pid="x"):
    return {"id": pid, "name": name, "address": address}


class HelperTests(TestCase):
    def test_accents_and_neighborhood_tags_are_ignored(self):
        self.assertEqual(
            normalize_name("OLIO E PIÙ East Village", drop_places=True), "OLIO E PIU"
        )

    def test_google_address_parts(self):
        addr = "12 E 4th St, New York, NY 10003, USA"
        self.assertEqual(google_zip(addr), "10003")
        self.assertEqual(google_street(addr), "E 4 ST")


class AttachInspectionsTests(TestCase):
    def test_exact_name_and_zip_matches(self):
        inspect("1", "CAFE MOGADOR", "AVENUE A", "10009", grade="A")
        result = attach_inspections(
            [place("Cafe Mogador", "101 Avenue A, New York, NY 10009")]
        )
        self.assertEqual(result[0]["inspection"]["camis"], "1")
        self.assertEqual(result[0]["inspection"]["grade"], "A")

    def test_partial_name_needs_the_same_street(self):
        inspect("2", "GNOCCHERIA", "EAST 4 STREET", "10003")
        same = attach_inspections(
            [place("Gnoccheria Pasta Bar", "12 E 4th St, New York, NY 10003")]
        )
        other = attach_inspections(
            [place("Gnoccheria Pasta Bar", "12 Bleecker St, New York, NY 10003")]
        )
        self.assertEqual(same[0]["inspection"]["camis"], "2")
        self.assertIsNone(other[0]["inspection"])

    def test_no_match_gives_none(self):
        inspect("3", "SOME OTHER PLACE", "MAIN ST", "10003")
        result = attach_inspections(
            [place("Brand New Cafe", "1 Main St, New York, NY 10003")]
        )
        self.assertIsNone(result[0]["inspection"])

    def test_missing_zip_gives_none(self):
        result = attach_inspections([place("Cafe Mogador", "Somewhere")])
        self.assertIsNone(result[0]["inspection"])

    def test_two_places_for_one_restaurant_are_both_dropped(self):
        inspect("4", "ACME PIZZA", "BROADWAY", "10019")
        result = attach_inspections(
            [
                place("Acme Pizza", "1 Broadway, New York, NY 10019", pid="a"),
                place("Acme Pizza", "9 Broadway, New York, NY 10019", pid="b"),
            ]
        )
        self.assertTrue(all(r["inspection"] is None for r in result))
