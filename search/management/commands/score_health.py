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

from community.keys import GOOGLE
from community.models import HealthScore, PlaceEnrichment, Restaurant
from search import health_ai
from search.ai_scores import menu_texts as _menu_texts


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
            PlaceEnrichment.objects.filter(kind=GOOGLE)
            .exclude(place_id="")
            .prefetch_related("reviews")
            .order_by("key")
        )
        done = set()
        if not options["refresh"]:
            # Rows made before goal scores existed are scored again.
            done = set(
                HealthScore.objects.filter(goal_scores__isnull=False).values_list(
                    "place_id", flat=True
                )
            )
        todo = [p for p in places if p.place_id not in done]
        if options["limit"]:
            todo = todo[: options["limit"]]
        if not todo:
            self.stdout.write("Nothing to score.")
            return

        names = dict(
            Restaurant.objects.filter(
                place_id__in=[p.place_id for p in todo]
            ).values_list("place_id", "name")
        )
        self.stdout.write(f"Loading model {options['model']} ...")
        encoder = health_ai.load_encoder(options["model"], options["backend"])

        saved = skipped = 0
        for index, place in enumerate(todo, start=1):
            texts = [r.text for r in place.reviews.all() if (r.text or "").strip()]
            texts += _menu_texts(names.get(place.place_id) or place.display_name)
            score, used, goals = health_ai.all_scores(texts, encoder)
            if score is None:
                skipped += 1
                continue
            HealthScore.objects.update_or_create(
                place_id=place.place_id,
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
