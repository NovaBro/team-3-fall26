"""Write "why we recommend it" paragraphs with Gemini and store them.

Run on your Mac (not on the server), after ``score_health``:

    pip install -r requirements-ml.txt
    # put GEMINI_API_KEY=... in .env (free key from aistudio.google.com)
    python manage.py write_reasons --limit 5 --dry-run   # look, save nothing
    python manage.py write_reasons --limit 50            # save 50
    python manage.py write_reasons --refresh             # rewrite saved ones

Restaurants with an AI health score are done healthiest first. Only general
reasons go in (no user's favorites or home area, no Google review text).
The free Gemini tier has per-minute and per-day limits, so the command waits
``--sleep`` seconds between calls and stops cleanly if Gemini says the limit
is reached.
"""

import time

from django.core.management.base import BaseCommand

from community.models import HealthScore, PlaceEnrichment, ReasonBlurb
from search import reason_writer
from search.models import RestaurantInspection
from search.views import score_for_camis


class Command(BaseCommand):
    help = "Write reason paragraphs with Gemini (run locally)."
    stealth_options = ("generate",)  # tests pass a fake writer

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50, help="Stop after N.")
        parser.add_argument(
            "--refresh", action="store_true", help="Rewrite saved paragraphs."
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Print only; save nothing."
        )
        parser.add_argument("--model", default=reason_writer.DEFAULT_MODEL)
        parser.add_argument(
            "--sleep", type=float, default=4.0, help="Seconds between calls."
        )

    def handle(self, *args, **options):
        generate = options.get("generate")
        todo = list(
            HealthScore.objects.order_by("-score").values_list("camis", flat=True)
        )
        if not options["refresh"]:
            done = {
                camis
                for camis, tag in ReasonBlurb.objects.values_list("camis", "model_name")
                if reason_writer.is_current(tag)
            }
            todo = [camis for camis in todo if camis not in done]
        if options["limit"]:
            todo = todo[: options["limit"]]
        if not todo:
            self.stdout.write("Nothing to write. Run score_health first?")
            return
        if generate is None:
            generate = reason_writer.gemini_generate(options["model"])

        written = skipped = 0
        for index, camis in enumerate(todo):
            latest = (
                RestaurantInspection.objects.filter(camis=camis)
                .order_by("-inspection_date")
                .first()
            )
            if latest is None:
                skipped += 1
                continue
            place = (
                PlaceEnrichment.objects.filter(camis=camis)
                .prefetch_related("reviews")
                .first()
            )
            _, _, breakdown = score_for_camis(camis, latest, place)
            reasons = breakdown["reasons"]
            if index and options["sleep"]:
                time.sleep(options["sleep"])
            try:
                text = reason_writer.write_blurb(
                    latest.dba, latest.cuisine, reasons, generate
                )
            except reason_writer.RateLimited:
                self.stdout.write(
                    self.style.WARNING("Gemini rate limit reached; stopping here.")
                )
                break
            if not text:
                skipped += 1
                continue
            self.stdout.write(f"{latest.dba}: {text}")
            written += 1
            if options["dry_run"]:
                continue
            ReasonBlurb.objects.update_or_create(
                camis=camis,
                defaults={
                    "text": text,
                    "facts": " · ".join(reasons),
                    "model_name": reason_writer.model_tag(options["model"]),
                },
            )
        action = "Would save" if options["dry_run"] else "Saved"
        self.stdout.write(
            self.style.SUCCESS(f"{action} {written} paragraphs; skipped {skipped}.")
        )
