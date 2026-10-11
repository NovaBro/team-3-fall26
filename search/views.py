from django.core.paginator import Paginator
from django.db.models import Max, Q, Subquery, OuterRef
from django.http import Http404
from django.shortcuts import render

from search.models import RestaurantInspection
from search.registry import DATASETS

PAGE_SIZE = 25

BOROUGHS = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"]
GRADES = ["A", "B", "C", "N", "P", "Z"]


def _filter_restaurants(qs, name, boro, zipcode, grade):
    if name:
        qs = qs.filter(dba__icontains=name)
    if boro:
        qs = qs.filter(boro=boro)
    if zipcode:
        qs = qs.filter(zipcode__startswith=zipcode)
    if grade:
        qs = qs.filter(grade=grade)
    return qs


def index(request):
    name = request.GET.get("q", "").strip()
    boro = request.GET.get("boro", "").strip()
    zipcode = request.GET.get("zip", "").strip()
    grade = request.GET.get("grade", "").strip()

    page_obj = None
    if name or boro or zipcode or grade:
        base = _filter_restaurants(
            RestaurantInspection.objects.all(), name, boro, zipcode, grade
        )
        latest = RestaurantInspection.objects.filter(
            camis=OuterRef("camis")
        ).order_by("-inspection_date")
        restaurants = (
            base.values("camis")
            .annotate(
                name=Max("dba"),
                boro=Max("boro"),
                street=Max("street"),
                zipcode=Max("zipcode"),
                last_date=Max("inspection_date"),
                grade=Subquery(latest.values("grade")[:1]),
            )
            .order_by("name")
        )
        page_obj = Paginator(restaurants, PAGE_SIZE).get_page(request.GET.get("page"))

    return render(
        request,
        "search/index.html",
        {
            "name": name,
            "boro": boro,
            "zip": zipcode,
            "grade": grade,
            "page_obj": page_obj,
            "boro_options": BOROUGHS,
            "grade_options": GRADES,
            "searched": bool(page_obj),
        },
    )


def restaurant_detail(request, camis):
    inspections = RestaurantInspection.objects.filter(camis=camis).order_by(
        "-inspection_date"
    )
    latest = inspections.first()
    if latest is None:
        raise Http404("Restaurant not found")
    return render(
        request,
        "search/restaurant_detail.html",
        {
            "camis": camis,
            "dba": latest.dba,
            "boro": latest.boro,
            "street": latest.street,
            "zipcode": latest.zipcode,
            "inspections": inspections,
        },
    )


def explore_index(request):
    return render(request, "search/explore_index.html", {"datasets": DATASETS})


def explore(request, slug):
    config = DATASETS.get(slug)
    if config is None:
        raise Http404("Unknown dataset")

    query = request.GET.get("q", "").strip()
    qs = config["model"].objects.order_by("pk")
    if query:
        condition = Q()
        for field in config["search_fields"]:
            condition |= Q(**{field: query})
        qs = qs.filter(condition)

    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [
        [
            "—" if getattr(obj, field) in (None, "") else getattr(obj, field)
            for field, _label in config["columns"]
        ]
        for obj in page_obj
    ]

    return render(
        request,
        "search/explore.html",
        {
            "config": config,
            "slug": slug,
            "query": query,
            "page_obj": page_obj,
            "columns": config["columns"],
            "rows": rows,
        },
    )
