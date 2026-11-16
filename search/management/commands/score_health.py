"""Compute AI health scores offline and store them in community.HealthScore.

Scores are also worked out on the fly the first time a place is shown (see
search/ai_scores.py); this command fills many places ahead of time:

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
from search.ai_scores import menu_texts as _menu_texts
from search.models import RestaurantInspection


def _camis(key):
    return key.split(":", 1)[1] if key.startswith("camis:") else ""


class Command(BaseCommand):
    help = "Compute AI health scores from reviews/menus (run locally)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Stop after N.")
        parser.add_argument(
            "--refresh", action="store_true", help="Recompute existing scores."
        )
        parser.add_argument("--model", default=health_ai.MODEL_NAME)
        parser.add_argument(
            "--backend",
            default="auto",
            choices=["auto", "fastembed", "sentence-transformers"],
            help="auto: fastembed if installed, else sentence-transformers.",
        )

    def handle(self, *args, **options):
        places = (
            PlaceEnrichment.objects.filter(kind=DOHMH, key__startswith="camis:")
            .prefetch_related("reviews")
            .order_by("key")
        )
        done = set()
        if not options["refresh"]:
            # Rows made before goal scores existed are scored again.
            done = set(
                HealthScore.objects.filter(goal_scores__isnull=False).values_list(
                    "camis", flat=True
                )
            )
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
        encoder = health_ai.load_encoder(options["model"], options["backend"])

        saved = skipped = 0
        for index, place in enumerate(todo, start=1):
            camis = _camis(place.key)
            texts = [r.text for r in place.reviews.all() if (r.text or "").strip()]
            texts += _menu_texts(names.get(camis) or place.display_name)
            score, used, goals = health_ai.all_scores(texts, encoder)
            if score is None:
                skipped += 1
                continue
            HealthScore.objects.update_or_create(
                camis=camis,
                defaults={
                    "score": score,
                    "sentences_used": used,
                    "goal_scores": goals,
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
