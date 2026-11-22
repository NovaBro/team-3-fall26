"""Estimate menus with Gemini for restaurants without a MenuStat menu.

Run on your Mac (not on the server):

    # put GEMINI_API_KEY=... in .env (free key from aistudio.google.com)
    python manage.py estimate_menus --limit 5 --dry-run   # look, save nothing
    python manage.py estimate_menus                       # all missing ones
    python manage.py estimate_menus --refresh             # redo saved ones

Restaurants come from the Google-backed pool (community.Restaurant). MenuStat
chains are skipped: they have a real menu. Several
restaurants go in one Gemini call (``--batch``); the command waits
``--sleep`` seconds between calls and stops cleanly at the rate limit, so a
re-run picks up where it stopped.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from community.models import MenuEstimate, Restaurant
from search import menu_estimate
from search.menustat import match_menustat_restaurant


class Command(BaseCommand):
    help = "Estimate menus (dishes + calories) with Gemini (run locally)."
    stealth_options = ("generate",)  # tests pass a fake Gemini

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=0, help="Stop after N (0 = all)."
        )
        parser.add_argument(
            "--batch", type=int, default=5, help="Restaurants per Gemini call."
        )
        parser.add_argument(
            "--sleep", type=float, default=4.0, help="Seconds between calls."
        )
        parser.add_argument(
            "--refresh", action="store_true", help="Redo saved estimates."
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Print only; save nothing."
        )
        parser.add_argument(
            "--model", default="", help="Gemini model (default: settings)."
        )

    def handle(self, *args, **options):
        model = options["model"] or settings.GEMINI_MODEL
        rows = list(
            Restaurant.objects.filter(business_status__in=(Restaurant.OPERATIONAL, ""))
            .order_by("place_id")
            .values("place_id", "name", "cuisine", "boro", "street")
        )
        menustat = [r for r in rows if match_menustat_restaurant(r["name"])]
        todo = [r for r in rows if not match_menustat_restaurant(r["name"])]
        if not options["refresh"]:
            done = {
                place_id
                for place_id, tag in MenuEstimate.objects.values_list(
                    "place_id", "model_name"
                )
                if menu_estimate.is_current(tag)
            }
            todo = [r for r in todo if r["place_id"] not in done]
        if options["limit"]:
            todo = todo[: options["limit"]]
        self.stdout.write(
            f"{len(rows)} restaurants, {len(menustat)} with MenuStat; "
            f"{len(todo)} to estimate."
        )
        if not todo:
            return

        generate = options.get("generate") or menu_estimate.gemini_generate(model)
        size = max(1, options["batch"])
        saved = skipped = 0
        for start in range(0, len(todo), size):
            chunk = todo[start : start + size]  # noqa: E203 (black slice style)
            batch = [{**r, "id": r["place_id"]} for r in chunk]
            if start and options["sleep"]:
                time.sleep(options["sleep"])
            try:
                result = menu_estimate.estimate_batch(batch, generate)
            except menu_estimate.RateLimited:
                self.stdout.write(
                    self.style.WARNING("Gemini rate limit reached; stopping here.")
                )
                break
            except Exception as exc:  # one bad batch shouldn't stop the run
                self.stdout.write(self.style.WARNING(f"Batch failed: {exc}"))
                skipped += len(batch)
                continue
            for row in batch:
                items = result.get(row["place_id"])
                if not items:
                    skipped += 1
                    continue
                median, mains = menu_estimate.summarize(items)
                kcal = "n/a" if median is None else f"~{median:.0f} kcal"
                self.stdout.write(f"{row['name']}: {len(items)} items, mains {kcal}")
                saved += 1
                if options["dry_run"]:
                    for item in items[:5]:
                        self.stdout.write(
                            f"    {item['kind']:<7} {item['name']} "
                            f"({item['calories']} kcal)"
                        )
                    continue
                MenuEstimate.objects.update_or_create(
                    place_id=row["place_id"],
                    defaults={
                        "items": items,
                        "median_calories": median,
                        "meal_count": mains,
                        "model_name": menu_estimate.model_tag(model),
                    },
                )
        action = "Would save" if options["dry_run"] else "Saved"
        self.stdout.write(
            self.style.SUCCESS(f"{action} {saved} estimates; skipped {skipped}.")
        )
