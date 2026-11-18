"""Top picks show at most one branch of a chain."""

from django.test import SimpleTestCase

from search.recommend import pick_top


def item(name, cuisine, score):
    return {"name": name, "cuisine": cuisine, "score": score, "like_bonus": 0}


class OneBranchPerChainTests(SimpleTestCase):
    def test_second_branch_is_skipped(self):
        chosen = pick_top(
            [
                item("Just Salad", "Soups/Salads/Sandwiches", 0.9),
                item("JUST SALAD", "Salads", 0.85),
                item("Dig", "American", 0.8),
                item("Cava", "Mediterranean", 0.7),
            ]
        )
        self.assertEqual([c["name"] for c in chosen], ["Just Salad", "Dig", "Cava"])

    def test_refill_also_skips_the_chain(self):
        chosen = pick_top(
            [
                item("Sweetgreen", "Salads", 0.9),
                item("Chopt", "Salads", 0.8),
                item("Sweetgreen", "Salads", 0.7),
            ],
            count=3,
        )
        self.assertEqual([c["name"] for c in chosen], ["Sweetgreen", "Chopt"])
