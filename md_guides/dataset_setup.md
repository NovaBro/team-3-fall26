# Dataset setup and website usage

Raw NYC Open Data files live in `database/datasets/`, get bulk-loaded into SQLite by `import_datasets`, and power the `search` app. A separate `/restaurants/` flow uses live Google Places only and does not read the imported tables.

Filename suffix `YYYYMMDD` (e.g. `20261011`) is the **download date**, not a content/coverage date. Dataset contents may reference older periods (e.g. 2017–2026).

## Datasets on disk

| File | Approx. size | Role | Key fields |
|------|--------------|------|------------|
| `restaurant_data_set_2_*.csv` | ~71M | DOHMH restaurant inspections | `CAMIS`, `DBA`, `BORO`, `STREET`, `ZIPCODE`, `INSPECTION DATE`, `VIOLATION CODE`, `VIOLATION DESCRIPTION`, `GRADE` |
| `DOHMH_MenuStat_(Historical)_*.csv` | ~21M | Chain menu nutrition (MenuStat) | `Restaurant_ID`, `Menu_Item_ID`, nutrients per serving / per 100g, kids/LTO flags |
| `Good_Food_Purchasing_Data_*.csv` | ~3.5M | Agency food purchases | agency, product, vendor, units / weight / cost |
| `NYC_Farmers_Markets_*.csv` | ~297K | Farmers markets | name, borough, lat/long, hours, season, EBT |
| `Recognized_Shop_Healthy_Stores_*.csv` | ~101K | Shop Healthy stores | store, address, lat/long, program wave, geo IDs |
| `DPR_Eateries_001.json` | ~52K (142 rows) | Park eateries | `name`, `location`, `park_id`, `permit_number`, `website`, `type_name` |

There is **no shared primary key** across sources: inspection `CAMIS` and MenuStat `Restaurant_ID` are distinct ID spaces.

## Import / ETL

Rebuild the database anytime:

```bash
.venv/bin/python manage.py import_datasets
```

Implemented in `search/management/commands/import_datasets.py`. The command is idempotent.

### Flow

1. Resolve the latest file matching each glob under `database/datasets/`
2. Delete all rows in the target model (full reload)
3. Read CSV via pandas (or JSON for DPR eateries); normalize text, zip codes, numbers, dates, and booleans
4. `bulk_create` in batches of 2000 into SQLite at `database/nyc_food.db` (generated, not committed)

### Source → Django model

| Dataset | Model (`search/models.py`) |
|---------|----------------------------|
| `restaurant_data_set_2_*.csv` | `RestaurantInspection` |
| `DOHMH_MenuStat_(Historical)_*.csv` | `MenuItem` |
| `Good_Food_Purchasing_Data_*.csv` | `AgencyPurchase` |
| `NYC_Farmers_Markets_*.csv` | `FarmersMarket` |
| `Recognized_Shop_Healthy_Stores_*.csv` | `HealthyStore` |
| `DPR_Eateries_*.json` | `ParkEatery` |

**Partial MenuStat import:** most `*_100g` nutrients (except `Calories_100g`), serving-size helper columns, and `*_text` nutrient columns are dropped at import time.

## How the website uses the data

### Restaurant inspections (first-class UI)

| Path | Behavior |
|------|----------|
| `/` | Filter by name, borough, ZIP, or grade; one result row per `camis` with the latest grade |
| `/restaurant/<camis>/` | Full inspection / violation history for that restaurant |
| `POST /restaurant/<camis>/refresh-google/` | Fetch and cache Google Places data, then redirect to the detail page |

Logic lives in `search/views.py` (`index`, `restaurant_detail`, `refresh_place`).

### Other open-data tables (generic browser)

`search/registry.py` maps URL slugs to models, display columns, and search fields. Restaurant inspections are **not** in this registry; they use the dedicated views above.

| Slug | Model | Search fields |
|------|-------|---------------|
| `menu-items` | `MenuItem` | restaurant, item name |
| `agency-purchases` | `AgencyPurchase` | agency, product, vendor |
| `farmers-markets` | `FarmersMarket` | market name, street address |
| `healthy-stores` | `HealthyStore` | store name, street address |
| `park-eateries` | `ParkEatery` | name, location, type |

| Path | Behavior |
|------|----------|
| `/explore/` | Cards listing the five registry datasets |
| `/explore/<slug>/` | Paginated table (25/page) with text search |

### Farmers markets map

`/farmers-markets/` loads the latest year of `FarmersMarket`, filters to NYC lat/long bounds, supports name / ZIP / day-of-week filters (with day-range parsing), and applies a hard-coded location override for one market (`Saratoga Farm Stand`).

### Not from local datasets

`/restaurants/` (`restaurants/` app) queries Google Places at request time for area, price, diet, and distance filters. Results are **not** stored and do **not** use `database/datasets/` or `search` models.

## Google Places enrichment (cached)

Separate from the live `/restaurants/` search:

- **Service:** `search/services/places.py` (`enrich_camis`)
- **Bulk CLI:** `search/management/commands/enrich_places.py`
- **Models:** `PlaceEnrichment` and `PlaceReview`, keyed by `camis`

Flow for one restaurant:

1. Load the latest `RestaurantInspection` for the `camis`
2. Text Search (`dba` + address) with NYC bias → place id
3. Place Details → rating, price, website, reviews, lat/long
4. Persist to `PlaceEnrichment` and replace related `PlaceReview` rows

Needs `GOOGLE_PLACES_API_KEY`. UI: **Get Google data** on the restaurant detail page. CLI example:

```bash
export GOOGLE_PLACES_API_KEY="your-key"
.venv/bin/python manage.py enrich_places --limit 25 --sleep 0.5
```

`--refresh` overwrites existing enrichments. Each restaurant costs two API calls (Text Search + Place Details); afterward, detail pages serve cached data from SQLite.

## Data flow

```
database/datasets/*
        │
        ▼
  import_datasets  ──►  SQLite (database/nyc_food.db)
                              │
                              ├── /  + /restaurant/<camis>/
                              ├── /explore/...
                              └── /farmers-markets/

Google Places API
        │
        ├── enrich_places / refresh-google  ──►  PlaceEnrichment (+ reviews on detail)
        └── /restaurants/ (request-time only, not stored)
```

## Setup reminder

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_datasets   # loads CSVs/JSON into database/nyc_food.db
.venv/bin/python manage.py runserver
```

Open http://127.0.0.1:8000/.

## Gaps and caveats

- Datasets are not joined to each other (`CAMIS` vs MenuStat `Restaurant_ID` never linked).
- MenuStat is only partially imported (many CSV columns dropped).
- Google enrichment is on-demand (detail-page click or CLI), not automatic for all restaurants.
- Two Places paths exist: cached enrichment in `search` vs live search in `restaurants`; they do not share storage or the same env-key naming (`GOOGLE_PLACES_API_KEY` vs `GOOGLE_API_KEY` / `GOOGLE_MAPS_JS_KEY`).
- `AGENTS.md` may still describe a pre-Django repo state; prefer this guide and `README.md` for current architecture.
