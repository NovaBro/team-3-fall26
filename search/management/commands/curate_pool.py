"""Keep only the best rated places per borough in the ranked pool.

Sets the ``active`` flag on restaurants, farmers markets and Shop Healthy
stores (see search/curation.py for the scoring). Nothing is deleted and no
Google requests are made, so it is free to re-run.

Usage:
    python manage.py curate_pool                      # 500 per borough each
    python manage.py curate_pool --per-borough 300 --dry-run
    python manage.py curate_pool --kind restaurants
"""

from django.core.management.base import BaseCommand, CommandError

from search.curation import KINDS, PER_BOROUGH, curate


def write_report(stdout, report):
    for kind, boroughs in report.items():
        kept = sum(k for k, _ in boroughs.values())
        total = sum(t for _, t in boroughs.values())
        stdout.write(f"{kind}: {kept:,} of {total:,} active")
        for borough, (k, t) in boroughs.items():
            stdout.write(f"  {borough or '(no borough)'}: {k:,} / {t:,}")


class Command(BaseCommand):
    help = "Mark the top rated places per borough as active (no deletes)."

    def add_arguments(self, parser):
        parser.add_argument("--per-borough", type=int, default=PER_BOROUGH)
        parser.add_argument("--kind", action="append", choices=KINDS, dest="kinds")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["per_borough"] < 1:
            raise CommandError("--per-borough must be a positive integer.")
        report = curate(
            kinds=options["kinds"] or KINDS,
            per_borough=options["per_borough"],
            dry_run=options["dry_run"],
        )
        write_report(self.stdout, report)
        if options["dry_run"]:
            self.stdout.write("Dry run: nothing changed.")
