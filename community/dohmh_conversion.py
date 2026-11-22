"""One-time move from DOHMH inspection ids (CAMIS) to Google place ids.

Restaurants used to be identified by their NYC inspection record (CAMIS) and
Google data hung off that id. Now Google Places is the only restaurant source,
so every restaurant row in community.db is re-keyed to its Google place id:

- ``PlaceEnrichment`` / ``CommunitySubject`` (kind ``restaurant_dohmh``, key
  ``camis:<id>``) become kind ``restaurant_google``, key ``google:<place_id>``.
- ``RecommendationFeedback``, ``HealthScore``, ``ReasonBlurb`` and
  ``MenuEstimate`` (already renamed to ``place_id`` by the migration, still
  holding CAMIS values) get the place id.
- Each enriched restaurant becomes a ``Restaurant`` row, so the ranking pool
  is not empty before ``sync_restaurants`` runs. Cuisine, borough and street
  come from the inspection summary in the dataset DB when it is still there.

The CAMIS -> place id map comes from PlaceEnrichment (every enriched
restaurant has a place id). Rows that cannot be mapped are deleted. When
several CAMIS ids map to one place (food halls, renamed places), the most
recently fetched row wins. Called from community/migrations/0011.
"""

from django.db import connections

from restaurants.boroughs import borough_for_zip, zip_from_address

DOHMH = "restaurant_dohmh"
GOOGLE = "restaurant_google"


def _summary_rows(camis_ids):
    """{camis: (name, boro, street, zipcode, cuisine)} from the dataset DB.

    Empty when the inspection tables are gone (already migrated) or the
    database can't be read; the Restaurant rows then rely on Google data.
    """
    if not camis_ids:
        return {}
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT camis, name, boro, street, zipcode, cuisine "
                "FROM search_restaurantsummary"
            )
            rows = cursor.fetchall()
    except Exception:  # table missing, DB not there: no inspection data
        return {}
    wanted = set(camis_ids)
    return {row[0]: row[1:] for row in rows if row[0] in wanted}


def _place_map(PlaceEnrichment):
    """{camis: place_id}, plus the DOHMH enrichment rows newest first."""
    rows = list(
        PlaceEnrichment.objects.filter(kind=DOHMH)
        .exclude(place_id="")
        .order_by("-fetched_at", "-id")
    )
    mapping = {}
    for row in rows:
        camis = row.key.split(":", 1)[1] if row.key.startswith("camis:") else row.camis
        if camis:
            mapping.setdefault(camis, row.place_id)
    return mapping, rows


def _restaurant_fields(enrichment, summary):
    name, boro, street, zipcode, cuisine = summary or ("", "", "", "", "")
    address = enrichment.formatted_address or ""
    zipcode = zipcode or zip_from_address(address)
    return {
        "name": (enrichment.display_name or name or "")[:255],
        "address": address[:512],
        "street": (street or address.split(",", 1)[0])[:255],
        "zipcode": (zipcode or "")[:10],
        "boro": boro if boro and boro != "0" else borough_for_zip(zipcode),
        "cuisine": (cuisine or "")[:100],
        "latitude": enrichment.latitude,
        "longitude": enrichment.longitude,
        "rating": enrichment.rating,
        "rating_count": enrichment.user_rating_count,
        "price_level": enrichment.price_level or "",
        "business_status": enrichment.business_status or "",
        "maps_url": enrichment.google_maps_uri or "",
    }


def _rekey_enrichments(PlaceEnrichment, Restaurant, rows, summaries, seed):
    kept = set()
    for row in rows:  # newest first
        camis = row.key.split(":", 1)[1] if row.key.startswith("camis:") else row.camis
        new_key = f"google:{row.place_id}"
        if row.place_id in kept or (
            PlaceEnrichment.objects.filter(kind=GOOGLE, key=new_key).exists()
        ):
            row.delete()
            continue
        kept.add(row.place_id)
        row.kind, row.key = GOOGLE, new_key
        row.save(update_fields=["kind", "key"])
        if not Restaurant.objects.filter(place_id=row.place_id).exists():
            fields = _restaurant_fields(row, summaries.get(camis))
            Restaurant.objects.create(
                place_id=row.place_id, shuffle_seed=seed(row.place_id), **fields
            )
    # DOHMH rows Google never matched have no place id; nothing to keep.
    PlaceEnrichment.objects.filter(kind=DOHMH).delete()


def _merge_subject(old, target):
    """Move ratings, comments and photos of ``old`` onto ``target``."""
    rated = set(target.ratings.values_list("user_id", flat=True))
    for rating in old.ratings.all():
        if rating.user_id in rated:
            rating.delete()
        else:
            rating.subject = target
            rating.save(update_fields=["subject"])
    old.comments.update(subject=target)
    old.photos.update(subject=target)
    old.delete()


def _rekey_subjects(CommunitySubject, mapping):
    for subject in CommunitySubject.objects.filter(kind=DOHMH):
        camis = subject.key.split(":", 1)[1] if ":" in subject.key else ""
        place_id = mapping.get(camis)
        if not place_id:
            subject.delete()
            continue
        new_key = f"google:{place_id}"
        target = CommunitySubject.objects.filter(kind=GOOGLE, key=new_key).first()
        if target is not None:
            _merge_subject(subject, target)
            continue
        subject.kind, subject.key = GOOGLE, new_key
        subject.save(update_fields=["kind", "key"])


def _rekey_by_place_id(model, mapping, newest_field):
    """Rewrite ``place_id`` (holding a CAMIS) on a model with one row per place.

    ``newest_field`` decides which row wins when two CAMIS share a place id.
    Returns the number of rows dropped.
    """
    dropped = 0
    seen = set()
    for row in model.objects.order_by(f"-{newest_field}", "-id"):
        place_id = mapping.get(row.place_id)
        if not place_id or place_id in seen:
            row.delete()
            dropped += 1
            continue
        seen.add(place_id)
    # Second pass: ids are unique, so write after the duplicates are gone.
    for row in model.objects.all():
        place_id = mapping.get(row.place_id)
        if place_id:
            row.place_id = place_id
            row.save(update_fields=["place_id"])
    return dropped


def _rekey_feedback(RecommendationFeedback, mapping):
    seen = set()
    for row in RecommendationFeedback.objects.order_by("-updated_at", "-id"):
        place_id = mapping.get(row.place_id)
        if not place_id or (row.user_id, place_id) in seen:
            row.delete()
            continue
        seen.add((row.user_id, place_id))
    for row in RecommendationFeedback.objects.all():
        row.place_id = mapping[row.place_id]
        row.save(update_fields=["place_id"])


def convert(get_model, seed):
    """Re-key every restaurant row in community.db (see module docstring).

    ``get_model(name)`` returns a community model (the migration's historical
    models); ``seed(place_id)`` the Restaurant shuffle number.
    """
    PlaceEnrichment = get_model("PlaceEnrichment")
    Restaurant = get_model("Restaurant")
    mapping, rows = _place_map(PlaceEnrichment)
    summaries = _summary_rows(mapping)
    _rekey_enrichments(PlaceEnrichment, Restaurant, rows, summaries, seed)
    _rekey_subjects(get_model("CommunitySubject"), mapping)
    _rekey_feedback(get_model("RecommendationFeedback"), mapping)
    _rekey_by_place_id(get_model("HealthScore"), mapping, "computed_at")
    _rekey_by_place_id(get_model("ReasonBlurb"), mapping, "computed_at")
    _rekey_by_place_id(get_model("MenuEstimate"), mapping, "computed_at")
    # Restaurant coordinates now live on Restaurant rows.
    get_model("LocationLookup").objects.filter(kind=DOHMH).delete()
