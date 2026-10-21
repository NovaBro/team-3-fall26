"""Diet and allergy filters shared by every restaurant search.

Allergies: no data source tells us what is actually in a restaurant's food, so these
filters only skip cuisines where the allergen is common. The UI must always
tell users to confirm allergies with the restaurant.

Each allergy lists:
    label:        text shown next to the checkbox
    google_types: Google Places types (primaryType / types) to skip
    cuisines:     DOHMH "CUISINE DESCRIPTION" values to skip (homepage search)
"""

ALLERGIES = {
    "nuts": {
        "label": "Avoid nut-heavy cuisines",
        "google_types": {
            "thai_restaurant",
            "indian_restaurant",
            "vietnamese_restaurant",
            "indonesian_restaurant",
            "chinese_restaurant",
            "african_restaurant",
            "lebanese_restaurant",
            "middle_eastern_restaurant",
            "bakery",
            "dessert_shop",
            "donut_shop",
            "ice_cream_shop",
        },
        "cuisines": {
            "Thai",
            "Indian",
            "Pakistani",
            "Bangladeshi",
            "Southeast Asian",
            "Indonesian",
            "Asian/Asian Fusion",
            "Chinese",
            "Chinese/Cuban",
            "Chinese/Japanese",
            "African",
            "Lebanese",
            "Middle Eastern",
            "Bakery Products/Desserts",
            "Donuts",
            "Frozen Desserts",
            "Nuts/Confectionary",
        },
    },
    "shellfish": {
        "label": "Avoid shellfish-heavy cuisines",
        "google_types": {
            "seafood_restaurant",
            "sushi_restaurant",
            "japanese_restaurant",
            "thai_restaurant",
            "vietnamese_restaurant",
            "chinese_restaurant",
            "indonesian_restaurant",
            "spanish_restaurant",
        },
        "cuisines": {
            "Seafood",
            "Japanese",
            "Chinese/Japanese",
            "Thai",
            "Southeast Asian",
            "Indonesian",
            "Filipino",
            "Chinese",
            "Chinese/Cuban",
            "Asian/Asian Fusion",
            "Cajun",
            "Creole",
            "Creole/Cajun",
            "Spanish",
            "Tapas",
        },
    },
}

# Diets are matched to restaurants that specialize in them.
#   cuisines:     DOHMH cuisines for the homepage search (None = not offered there)
#   google:       how /restaurants/ asks Google (None = not offered there)
#       query:    words used in the Text Search query
#       type:     strict Google place type, if one exists
# Vegetarian on Google is also checked against servesVegetarianFood (places.py).
# Keto has no cuisine or place type, so it relies on Google's text matching and
# on low-carb-leaning cuisines; both are approximate.
DIETS = {
    "vegetarian": {
        "label": "Vegetarian",
        "cuisines": {"Vegetarian", "Vegan"},
        "google": {"query": "vegetarian restaurants", "type": None},
    },
    "vegan": {
        "label": "Vegan",
        "cuisines": {"Vegan"},
        "google": {"query": "vegan restaurants", "type": "vegan_restaurant"},
    },
    "pescatarian": {
        "label": "Pescatarian",
        "cuisines": {"Seafood", "Vegetarian", "Vegan"},
        "google": {"query": "seafood restaurants", "type": "seafood_restaurant"},
    },
    "keto": {
        "label": "Keto",
        "cuisines": {"Steakhouse", "Barbecue", "Seafood"},
        "google": {"query": "keto-friendly restaurants", "type": None},
    },
    "halal": {
        "label": "Halal",
        "cuisines": None,
        "google": {"query": "halal restaurants", "type": "halal_restaurant"},
    },
    "kosher": {
        "label": "Kosher",
        "cuisines": {"Jewish/Kosher"},
        "google": None,
    },
}

ALLERGY_CHOICES = [(key, a["label"]) for key, a in ALLERGIES.items()]
HOMEPAGE_DIET_CHOICES = [(key, d["label"]) for key, d in DIETS.items() if d["cuisines"]]
GOOGLE_DIET_CHOICES = [(key, d["label"]) for key, d in DIETS.items() if d["google"]]


def risky_google_types(avoid):
    """Union of Google place types to skip for the given allergy keys."""
    return set().union(*(ALLERGIES[key]["google_types"] for key in avoid))


def risky_cuisines(avoid):
    """Union of DOHMH cuisine descriptions to skip for the given allergy keys."""
    return set().union(*(ALLERGIES[key]["cuisines"] for key in avoid))
