"""Which NYC borough a Google place is in."""

import re

BOROUGHS = ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")

# ZIP prefix -> borough, for addresses Google gives no borough for.
ZIP_BOROUGHS = (
    (("100", "101", "102"), "Manhattan"),
    (("103",), "Staten Island"),
    (("104",), "Bronx"),
    (("112",), "Brooklyn"),
    (("110", "111", "113", "114", "116"), "Queens"),
)
# Google's sublocality names -> our borough names.
SUBLOCALITY_BOROUGHS = {
    "manhattan": "Manhattan",
    "new york": "Manhattan",
    "brooklyn": "Brooklyn",
    "queens": "Queens",
    "bronx": "Bronx",
    "the bronx": "Bronx",
    "staten island": "Staten Island",
}


def borough_for_zip(zipcode):
    for prefixes, boro in ZIP_BOROUGHS:
        if (zipcode or "").startswith(prefixes):
            return boro
    return ""


def zip_from_address(address):
    matches = ZIP_RE.findall(address or "")
    return matches[-1] if matches else ""


def address_component(components, kind):
    """``longText`` of the first Google address component of ``kind``."""
    return next(
        (
            item.get("longText", "")
            for item in components or ()
            if kind in item.get("types", [])
        ),
        "",
    )


def borough_for_place(components, zipcode=""):
    """Borough from Google address components, else from the ZIP code."""
    for kind in ("sublocality_level_1", "sublocality", "locality"):
        name = address_component(components, kind).casefold()
        if name in SUBLOCALITY_BOROUGHS:
            return SUBLOCALITY_BOROUGHS[name]
    return borough_for_zip(zipcode)
