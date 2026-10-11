"""Metadata that drives the generic dataset browser.

Each entry maps a URL slug to a model, the columns shown in the table, and the
fields searched when the user submits a text query. Restaurant inspections are
handled separately by a dedicated search view.
"""

from search.models import (
    AgencyPurchase,
    FarmersMarket,
    HealthyStore,
    MenuItem,
    ParkEatery,
)

DATASETS = {
    "menu-items": {
        "title": "Menu Nutrition Stats",
        "model": MenuItem,
        "description": "MenuStat nutrition for large chain restaurant menu items (2017-2018).",
        "columns": [
            ("restaurant", "Restaurant"),
            ("item_name", "Item"),
            ("food_category", "Category"),
            ("year", "Year"),
            ("calories", "Calories"),
            ("total_fat", "Fat (g)"),
            ("sodium", "Sodium (mg)"),
            ("protein", "Protein (g)"),
        ],
        "search_fields": ["restaurant__icontains", "item_name__icontains"],
        "search_label": "restaurant or item",
    },
    "agency-purchases": {
        "title": "Agency Food Purchases",
        "model": AgencyPurchase,
        "description": "Good Food Purchasing Program purchases by NYC agencies.",
        "columns": [
            ("agency", "Agency"),
            ("time_period", "Period"),
            ("food_product_group", "Group"),
            ("product_name", "Product"),
            ("vendor", "Vendor"),
            ("units", "Units"),
            ("total_weight_lbs", "Weight (lbs)"),
            ("total_cost", "Cost ($)"),
        ],
        "search_fields": [
            "agency__icontains",
            "product_name__icontains",
            "product_type__icontains",
            "vendor__icontains",
        ],
        "search_label": "agency, product, or vendor",
    },
    "farmers-markets": {
        "title": "Farmers Markets",
        "model": FarmersMarket,
        "description": "NYC farmers markets with hours, season, and EBT availability.",
        "columns": [
            ("market_name", "Market"),
            ("borough", "Borough"),
            ("street_address", "Address"),
            ("days_of_operation", "Days"),
            ("season_dates", "Season"),
            ("accepts_ebt", "EBT"),
            ("open_year_round", "Year-round"),
        ],
        "search_fields": ["market_name__icontains", "street_address__icontains"],
        "search_label": "market or address",
    },
    "healthy-stores": {
        "title": "Shop Healthy Stores",
        "model": HealthyStore,
        "description": "Stores recognized by the Shop Healthy NYC program.",
        "columns": [
            ("store_name", "Store"),
            ("borough", "Borough"),
            ("street_address", "Address"),
            ("zip_code", "ZIP"),
            ("year_awarded", "Year Awarded"),
            ("program_wave", "Wave"),
        ],
        "search_fields": ["store_name__icontains", "street_address__icontains"],
        "search_label": "store or address",
    },
    "park-eateries": {
        "title": "Park Eateries",
        "model": ParkEatery,
        "description": "Permitted food eateries located in NYC parks.",
        "columns": [
            ("name", "Name"),
            ("location", "Location"),
            ("type_name", "Type"),
            ("permit_number", "Permit"),
            ("phone", "Phone"),
            ("website", "Website"),
        ],
        "search_fields": ["name__icontains", "location__icontains", "type_name__icontains"],
        "search_label": "name, location, or type",
    },
}
