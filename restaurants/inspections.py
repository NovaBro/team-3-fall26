"""Attach NYC health-inspection data to Google Places results.

Google results and the NYC inspection data share no ID, so we match on name
and ZIP code, and require the street to agree unless the names are identical.
A restaurant with no confident match simply shows no inspection data: showing
nothing is better than showing another restaurant's grade.
"""

import re
import unicodedata
from collections import defaultdict

from search.models import RestaurantInspection

# Neighborhood tags Google often adds to a restaurant's name.
PLACE_WORDS = [
    "EAST VILLAGE",
    "UPPER WEST SIDE",
    "UPPER WEST",
    "UWS",
    "ASTORIA",
    "WILLIAMSBURG",
    "MIDTOWN EAST",
    "MIDTOWN",
    "BRYANT PARK",
    "BROOKLYN",
    "NYC",
    "MANHATTAN",
]
STREET_ABBR = {
    "AVENUE": "AVE",
    "STREET": "ST",
    "BOULEVARD": "BLVD",
    "PLACE": "PL",
    "ROAD": "RD",
    "DRIVE": "DR",
    "EAST": "E",
    "WEST": "W",
    "NORTH": "N",
    "SOUTH": "S",
}
MIN_LOOSE_LEN = 5  # shortest name allowed for a partial (loose) name match


def _strip_accents(text):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(c)
    )


def normalize_name(text, drop_places=False):
    text = _strip_accents(text).upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if drop_places:
        for word in PLACE_WORDS:
            text = re.sub(rf"\b{word}\b", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_street(text):
    text = normalize_name(text)
    text = re.sub(r"\b(\d+)(ST|ND|RD|TH)\b", r"\1", text)
    return " ".join(STREET_ABBR.get(t, t) for t in text.split())


def google_street(address):
    """Street name from a Google address like '12 E 4th St, New York, NY 10003'."""
    first = (address or "").split(",")[0]
    first = re.sub(r"^\s*\d+[A-Z]?(-\d+)?\s+", "", first)
    return normalize_street(first)


def google_zip(address):
    match = re.search(r"NY (\d{5})", address or "")
    return match.group(1) if match else ""


def _restaurants_in_zip(zipcode):
    """One (camis, name, street) per restaurant in a ZIP code."""
    rows = (
        RestaurantInspection.objects.filter(zipcode=zipcode)
        .values_list("camis", "dba", "street")
        .distinct()
    )
    return list(rows)


def _match(name, address, candidates):
    """Return the matching camis, or None if there is no single confident match."""
    wanted = normalize_name(name, drop_places=True)
    street = google_street(address)
    exact, loose = set(), set()
    for camis, dba, nyc_street in candidates:
        nyc_name = normalize_name(dba, drop_places=True)
        if len(nyc_name) < 3:
            continue
        if nyc_name == wanted:
            exact.add(camis)
        elif (nyc_name in wanted or wanted in nyc_name) and min(
            len(nyc_name), len(wanted)
        ) >= MIN_LOOSE_LEN:
            if street and normalize_street(nyc_street) == street:
                loose.add(camis)
    found = exact or loose
    return next(iter(found)) if len(found) == 1 else None


def _latest(camis):
    rows = RestaurantInspection.objects.filter(camis=camis).order_by("-inspection_date")
    graded = rows.exclude(grade="").first()
    latest = rows.first()
    return {
        "camis": camis,
        "grade": graded.grade if graded else "",
        "date": (graded or latest).inspection_date if (graded or latest) else None,
    }


def attach_inspections(places):
    """Add an 'inspection' key (dict or None) to each Google place dict."""
    by_zip = {}
    matches = []
    for place in places:
        zipcode = google_zip(place.get("address"))
        if zipcode and zipcode not in by_zip:
            by_zip[zipcode] = _restaurants_in_zip(zipcode)
        camis = (
            _match(place["name"], place.get("address"), by_zip.get(zipcode, []))
            if zipcode
            else None
        )
        matches.append(camis)

    # Two Google places pointing at one NYC restaurant means at least one is wrong.
    owners = defaultdict(set)
    for place, camis in zip(places, matches):
        if camis:
            owners[camis].add(place.get("id") or place["name"])

    for place, camis in zip(places, matches):
        ambiguous = camis and len(owners[camis]) > 1
        place["inspection"] = _latest(camis) if camis and not ambiguous else None
    return places
