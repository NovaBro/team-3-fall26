"""Build RestaurantSummary rows (one per restaurant) from inspection rows.

The values are the ones the ranking used to work out on every visit:
the latest name, borough, street, ZIP and cuisine (MAX of each, as before),
the latest inspection date, and the grade of the latest graded inspection.
Restaurants whose rows all have a blank name are left out.

The model classes are passed in so the data migration can use its own
historical models.
"""

from django.db.models import Case, CharField, Max, Q, When
from django.db.models.functions import Cast, Concat, Right

BATCH = 2000


def aggregate_inspections(inspection_model, camis=None):
    """values() rows: camis, name, boro, street, zipcode, cuisine, last_date,
    latest_grade (one per restaurant)."""
    rows = inspection_model.objects.exclude(dba="")
    if camis is not None:
        rows = rows.filter(camis__in=list(camis))
    # Latest non-blank grade: max of "YYYY-MM-DD" + grade, then its last letter.
    dated_grade = Max(
        Case(
            When(
                ~Q(grade=""),
                then=Concat(Cast("inspection_date", CharField()), "grade"),
            ),
            output_field=CharField(),
        )
    )
    return (
        rows.values("camis")
        .annotate(
            name=Max("dba"),
            boro=Max("boro"),
            street=Max("street"),
            zipcode=Max("zipcode"),
            cuisine=Max("cuisine"),
            last_date=Max("inspection_date"),
            dated_grade=dated_grade,
        )
        .annotate(latest_grade=Right("dated_grade", 1))
        .values(
            "camis",
            "name",
            "boro",
            "street",
            "zipcode",
            "cuisine",
            "last_date",
            "latest_grade",
        )
        .order_by()
    )


def _summary(summary_model, row):
    return summary_model(
        camis=row["camis"],
        name=row["name"] or "",
        boro=row["boro"] or "",
        street=row["street"] or "",
        zipcode=row["zipcode"] or "",
        cuisine=row["cuisine"] or "",
        last_date=row["last_date"],
        latest_grade=row["latest_grade"] or "",
    )


def rebuild_all(inspection_model, summary_model, using="default"):
    """Replace every summary row. Returns the number of restaurants."""
    summary_model.objects.using(using).all().delete()
    batch, total = [], 0
    for row in aggregate_inspections(inspection_model).using(using).iterator():
        batch.append(_summary(summary_model, row))
        if len(batch) >= BATCH:
            summary_model.objects.using(using).bulk_create(batch)
            total += len(batch)
            batch = []
    if batch:
        summary_model.objects.using(using).bulk_create(batch)
        total += len(batch)
    return total


def refresh(inspection_model, summary_model, camis_values, using="default"):
    """Recompute the summary rows of these restaurants only."""
    camis_values = {str(c) for c in camis_values if c}
    if not camis_values:
        return
    rows = {
        row["camis"]: row
        for row in aggregate_inspections(inspection_model, camis_values).using(using)
    }
    summary_model.objects.using(using).filter(camis__in=camis_values).delete()
    summary_model.objects.using(using).bulk_create(
        [_summary(summary_model, row) for row in rows.values()]
    )
