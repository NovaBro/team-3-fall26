"""Compute AI health scores offline and store them in community.HealthScore.

Run on your Mac (not on the server):

    pip install -r requirements-ml.txt
    python manage.py score_health --limit 20      # quick try
    python manage.py score_health                  # every restaurant with text
    python manage.py score_health --refresh        # recompute existing rows

Text used per restaurant: its saved Google reviews (community.PlaceReview)
and, for chains in MenuStat, its meal names and descriptions.
"""

from django.core.management.base import BaseCommand
from django.db.models import Max

from community.keys import DOHMH
from community.models import HealthScore, PlaceEnrichment
from search import health_ai
from search.menustat import MEAL_CATEGORIES, match_menustat_restaurant
from search.models import MenuItem, RestaurantInspection


def _camis(key):
    return key.split(":", 1)[1] if key.startswith("camis:") else ""


def _menu_texts(name):
    chain = match_menustat_restaurant(name)
    if not chain:
        return []
    latest = MenuItem.objects.filter(restaurant=chain).aggregate(y=Max("year"))["y"]
    rows = MenuItem.objects.filter(
        restaurant=chain, year=latest, food_category__in=MEAL_CATEGORIES
    ).values_list("item_name", "item_description")
    return [f"{item}. {desc}".strip() for item, desc in rows if item]


class Command(BaseCommand):
    help = "Compute AI health scores from reviews/menus (run locally)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Stop after N.")
        parser.add_argument(
            "--refresh", action="store_true", help="Recompute existing scores."
        )
        parser.add_argument("--model", default=health_ai.MODEL_NAME)

    def handle(self, *args, **options):
        places = (
            PlaceEnrichment.objects.filter(kind=DOHMH, key__startswith="camis:")
            .prefetch_related("reviews")
            .order_by("key")
        )
        done = set()
        if not options["refresh"]:
            done = set(HealthScore.objects.values_list("camis", flat=True))
        todo = [p for p in places if _camis(p.key) and _camis(p.key) not in done]
        if options["limit"]:
            todo = todo[: options["limit"]]
        if not todo:
            self.stdout.write("Nothing to score.")
            return

        names = dict(
            RestaurantInspection.objects.filter(camis__in=[_camis(p.key) for p in todo])
            .values("camis")
            .annotate(name=Max("dba"))
            .values_list("camis", "name")
        )
        self.stdout.write(f"Loading model {options['model']} ...")
        encoder = health_ai.load_encoder(options["model"])

        saved = skipped = 0
        for index, place in enumerate(todo, start=1):
            camis = _camis(place.key)
            texts = [r.text for r in place.reviews.all() if (r.text or "").strip()]
            texts += _menu_texts(names.get(camis) or place.display_name)
            score, used = health_ai.restaurant_score(texts, encoder)
            if score is None:
                skipped += 1
                continue
            HealthScore.objects.update_or_create(
                camis=camis,
                defaults={
                    "score": score,
                    "sentences_used": used,
                    "model_name": options["model"],
                },
            )
            saved += 1
            if index % 25 == 0:
                self.stdout.write(f"  {index}/{len(todo)} ...")
        self.stdout.write(
            self.style.SUCCESS(
                f"Saved {saved} scores; skipped {skipped} with no health-related text."
            )
        )
