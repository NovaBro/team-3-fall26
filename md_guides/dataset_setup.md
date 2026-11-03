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

### Find food page (`/`)

Farmers markets (latest year), Shop Healthy stores, and restaurants (one row per
`camis`, newest grade) are shown together on one map and paginated list
(`search/find_food.py`, `search/views.py:index`). Rows without coordinates are
located through `PlaceEnrichment`, then `community.LocationLookup`, then a
Google Places Text Search for the visible page (`search/locations.py`). The
`locate_places` command backfills `LocationLookup`.

The MenuStat, agency purchase, and park eatery tables are still imported but are
no longer shown in the UI (the Explore datasets tab was removed in issue #109).

### Not from local datasets

Choosing **Google Places (live)** for restaurants on `/` queries Google Places at request time for area, price, diet, rating, open-now, and distance filters. Those results are **not** stored.

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
                              ├── /  (Find food map + list)
                              └── /restaurant/<camis>/

Google Places API
        │
        ├── enrich_places / refresh-google  ──►  PlaceEnrichment (+ reviews on detail)
        ├── / with Google Places source (request-time only, not stored)
        └── / missing locations ──►  LocationLookup (30-day cache)
```

## Setup reminder

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
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
