"""Turn Google place types into the cuisine labels the ranking code uses.

Scoring (search/recommend.py), allergy filters (restaurants/diet_filters.py),
profile foods (search/profile_options.py) and the assistant all work with one
set of cuisine labels, such as "Chinese", "Coffee/Tea" or "Juice, Smoothies,
Fruit Salads" (originally NYC's inspection data vocabulary). Google describes
a place with types such as ``chinese_restaurant`` or ``coffee_shop``; this
module picks the label for the most specific type a place has.
"""

import re

# Most specific first: a sushi place is also a japanese_restaurant.
TYPE_CUISINES = {
    "acai_shop": "Juice, Smoothies, Fruit Salads",
    "afghani_restaurant": "Afghan",
    "african_restaurant": "African",
    "american_restaurant": "American",
    "argentinian_restaurant": "Latin American",
    "asian_fusion_restaurant": "Asian/Asian Fusion",
    "asian_restaurant": "Asian/Asian Fusion",
    "australian_restaurant": "Australian",
    "bagel_shop": "Bagels/Pretzels",
    "bakery": "Bakery Products/Desserts",
    "bangladeshi_restaurant": "Bangladeshi",
    "barbecue_restaurant": "Barbecue",
    "brazilian_restaurant": "Brazilian",
    "breakfast_restaurant": "American",
    "brunch_restaurant": "American",
    "buffet_restaurant": "Sandwiches/Salads/Mixed Buffet",
    "burrito_restaurant": "Mexican",
    "cafe": "Coffee/Tea",
    "cafeteria": "American",
    "cajun_restaurant": "Cajun",
    "cake_shop": "Bakery Products/Desserts",
    "californian_restaurant": "Californian",
    "candy_store": "Nuts/Confectionary",
    "cantonese_restaurant": "Chinese",
    "caribbean_restaurant": "Caribbean",
    "chicken_restaurant": "Chicken",
    "chicken_wings_restaurant": "Chicken",
    "chinese_noodle_restaurant": "Chinese",
    "chinese_restaurant": "Chinese",
    "chocolate_shop": "Nuts/Confectionary",
    "coffee_shop": "Coffee/Tea",
    "colombian_restaurant": "Latin American",
    "confectionery": "Nuts/Confectionary",
    "cuban_restaurant": "Latin American",
    "deli": "Sandwiches",
    "dessert_restaurant": "Bakery Products/Desserts",
    "dessert_shop": "Bakery Products/Desserts",
    "dim_sum_restaurant": "Chinese",
    "diner": "American",
    "donut_shop": "Donuts",
    "dumpling_restaurant": "Chinese",
    "eastern_european_restaurant": "Eastern European",
    "ethiopian_restaurant": "Ethiopian",
    "european_restaurant": "Continental",
    "falafel_restaurant": "Middle Eastern",
    "filipino_restaurant": "Filipino",
    "fine_dining_restaurant": "New American",
    "fish_and_chips_restaurant": "Seafood",
    "french_restaurant": "French",
    "frozen_yogurt_shop": "Frozen Desserts",
    "fusion_restaurant": "Fusion",
    "gastropub": "American",
    "german_restaurant": "German",
    "greek_restaurant": "Greek",
    "gyro_restaurant": "Mediterranean",
    "halal_restaurant": "Middle Eastern",
    "hamburger_restaurant": "Hamburgers",
    "hawaiian_restaurant": "Hawaiian",
    "hot_dog_restaurant": "Hotdogs",
    "hot_dog_stand": "Hotdogs",
    "ice_cream_shop": "Frozen Desserts",
    "indian_restaurant": "Indian",
    "indonesian_restaurant": "Indonesian",
    "irish_pub": "Irish",
    "irish_restaurant": "Irish",
    "italian_restaurant": "Italian",
    "japanese_curry_restaurant": "Japanese",
    "japanese_restaurant": "Japanese",
    "juice_shop": "Juice, Smoothies, Fruit Salads",
    "korean_barbecue_restaurant": "Korean",
    "korean_restaurant": "Korean",
    "latin_american_restaurant": "Latin American",
    "lebanese_restaurant": "Lebanese",
    "mediterranean_restaurant": "Mediterranean",
    "mexican_restaurant": "Mexican",
    "middle_eastern_restaurant": "Middle Eastern",
    "moroccan_restaurant": "Moroccan",
    "noodle_shop": "Asian/Asian Fusion",
    "pakistani_restaurant": "Pakistani",
    "pastry_shop": "Bakery Products/Desserts",
    "persian_restaurant": "Iranian",
    "peruvian_restaurant": "Peruvian",
    "pizza_delivery": "Pizza",
    "pizza_restaurant": "Pizza",
    "polish_restaurant": "Polish",
    "portuguese_restaurant": "Portuguese",
    "pub": "Irish",
    "ramen_restaurant": "Japanese",
    "russian_restaurant": "Russian",
    "salad_shop": "Salads",
    "sandwich_shop": "Sandwiches",
    "scandinavian_restaurant": "Scandinavian",
    "seafood_restaurant": "Seafood",
    "soul_food_restaurant": "Soul Food",
    "soup_restaurant": "Soups",
    "south_american_restaurant": "Latin American",
    "southwestern_us_restaurant": "Southwestern",
    "spanish_restaurant": "Spanish",
    "steak_house": "Steakhouse",
    "sushi_restaurant": "Japanese",
    "taco_restaurant": "Mexican",
    "taiwanese_restaurant": "Chinese",
    "tapas_restaurant": "Tapas",
    "tea_house": "Coffee/Tea",
    "tex_mex_restaurant": "Tex-Mex",
    "thai_restaurant": "Thai",
    "turkish_restaurant": "Turkish",
    "vegan_restaurant": "Vegan",
    "vegetarian_restaurant": "Vegetarian",
    "vietnamese_restaurant": "Southeast Asian",
    "western_restaurant": "American",
    "wine_bar": "American",
}

# Types that say nothing about the food: they never set a cuisine.
GENERIC_TYPES = {
    "restaurant",
    "food",
    "food_store",
    "point_of_interest",
    "establishment",
    "store",
    "bar",
    "bar_and_grill",
    "meal_takeaway",
    "meal_delivery",
    "fast_food_restaurant",
    "catering_service",
    "food_court",
    "grocery_store",
    "supermarket",
    "convenience_store",
    "market",
}

_SUFFIX = re.compile(r"_restaurant$")


def cuisine_for_types(primary_type="", types=()):
    """Cuisine label for a Google place, or "" when its types are all generic.

    The primary type wins when it names a cuisine; otherwise the first other
    type that does. Unknown specific types (Google adds new ones) become their
    own label, e.g. ``uzbek_restaurant`` -> "Uzbek".
    """
    ordered = [primary_type, *sorted(types or ())]
    for kind in ordered:
        if kind in TYPE_CUISINES:
            return TYPE_CUISINES[kind]
    for kind in ordered:
        if kind and kind not in GENERIC_TYPES and _SUFFIX.search(kind):
            return _SUFFIX.sub("", kind).replace("_", " ").title()
    return ""
