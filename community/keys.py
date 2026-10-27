"""Stable pin identities. These survive a dataset reimport."""

DOHMH = "restaurant_dohmh"
GOOGLE = "restaurant_google"
GROCERY = "grocery"
FARMERS_MARKET = "farmers_market"

KINDS = {DOHMH, GOOGLE, GROCERY, FARMERS_MARKET}


def _part(value):
    return " ".join(str(value or "").replace("/", " ").split())


def _join(*parts):
    return "|".join(_part(part) for part in parts)


def dohmh_key(camis):
    return f"camis:{_part(camis)}"


def google_key(place_id):
    return f"google:{_part(place_id)}"


def grocery_key(name, street, zipcode):
    return _join(name, street, zipcode)


def farmers_market_key(year, name, street):
    return _join(year, name, street)
