# Dataset setup and website usage

Raw NYC Open Data files live in `database/datasets/`, get bulk-loaded into SQLite by `import_datasets`, and power the `search` app. A separate `/restaurants/` flow uses live Google Places only and does not read the imported tables.

Filename suffix `YYYYMMDD` (e.g. `20261011`) is the **download date**, not a content/coverage date. Dataset contents may reference older periods (e.g. 2017–2026).

## Datasets on disk

| File | Approx. size | Rows | Role | Key fields |
|------|--------------|------|------|------------|
| `restaurant_data_set_2_*.csv` | ~71M | ~297K | DOHMH restaurant inspections (one row per violation) | `CAMIS`, `DBA`, `BORO`, `STREET`, `ZIPCODE`, `INSPECTION DATE`, `VIOLATION CODE`, `VIOLATION DESCRIPTION`, `GRADE` |
| `DOHMH_MenuStat_(Historical)_*.csv` | ~21M | ~65K | Chain menu nutrition (MenuStat) | `Restaurant_ID`, `Menu_Item_ID`, nutrients per serving / per 100g, kids/LTO flags |
| `NYC_Farmers_Markets_*.csv` | ~300K | ~2.3K | Farmers markets | name, borough, lat/long, hours, season, EBT |
| `Recognized_Shop_Healthy_Stores_*.csv` | ~104K | 712 | Shop Healthy stores | store, address, lat/long, program wave, geo IDs |
| `restaurant_cuisines_*.csv` | ~688K | ~31.5K | CAMIS → cuisine lookup (from Open Data `43nn-pn8j`) | `camis`, `cuisine_description` |

Total: about 93 MB / 397K rows.

There is **no shared primary key** across sources: inspection `CAMIS` and MenuStat `Restaurant_ID` are distinct ID spaces. Inspections are linked to MenuStat by fuzzy name match (`search/menustat.py`).

## Import / ETL

Rebuild the database anytime:

```bash
.venv/bin/python manage.py import_datasets
```

Implemented in `search/management/commands/import_datasets.py`. The command is idempotent.

`import_datasets` always targets the **full** DB. If `database/nyc_food_lite.db`
exists, prefix it with `NYCFOOD_FULL_DATA=1` (it refuses to run otherwise).

### Lite DB

`manage.py build_lite_db [--limit 500] [--force]`
(`search/management/commands/build_lite_db.py`) writes `database/nyc_food_lite.db`:
a copy of the full DB pruned to the top 500 restaurants (spread by borough), 500
Shop Healthy stores, and ≤500 farmers markets per year.

- **Ranking:** places are ranked by a Bayesian-average Google rating from
  `community_placeenrichment`: `(v·R + 50·C) / (v + 50)`, where `v` is the number
  of reviews, `R` the place's rating and `C` the mean rating. Places without Google
  data rank last; restaurants among them are ordered by grade A first, then the
  newest inspection.
- **Excluded:** places Google lists as closed, and restaurants whose latest grade
  is C.
- **Which DB the site uses:** settings use the lite file when it exists;
  `NYCFOOD_FULL_DATA=1` switches back. Nothing is deleted.
- **Speed:** measured locally as an anonymous user, the home/Top Picks page went
  from ~0.35 s to ~0.085 s and an empty search from ~0.7 s to ~0.28 s.

### Flow

1. Resolve the latest file matching each glob under `database/datasets/`
2. Delete all rows in the target model (full reload)
3. Read CSV via pandas; normalize text, zip codes, numbers, dates, and booleans
4. `bulk_create` in batches of 2000 into SQLite at `database/nyc_food.db` (generated, not committed)

### Source → Django model

| Dataset | Model (`search/models.py`) |
|---------|----------------------------|
| `restaurant_data_set_2_*.csv` | `RestaurantInspection` |
| `restaurant_cuisines_*.csv` | `RestaurantInspection.cuisine` (matched on CAMIS) |
| `DOHMH_MenuStat_(Historical)_*.csv` | `MenuItem` |
| `NYC_Farmers_Markets_*.csv` | `FarmersMarket` |
| `Recognized_Shop_Healthy_Stores_*.csv` | `HealthyStore` |

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

MenuStat is not listed on its own, but it feeds Top Picks ranking, health-goal
fit, the "what to order" menu box, and lower-calorie items on restaurant detail
pages (`search/recommend.py`, `search/goal_fit.py`, `search/what_to_order.py`).
The Good Food Purchasing and DPR park eatery datasets were dropped: nothing
read them after the Explore datasets tab was removed in issue #109.

Accounts are not in this database: they live in `database/users.db`
(`nycfood/routers.py`), so rebuilding `nyc_food.db` never touches them.

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

- No ID-based joins: inspections link to MenuStat only by fuzzy name match, so links can be wrong or missing.
- MenuStat is only partially imported (many CSV columns dropped).
- Google enrichment is on-demand (detail-page click or CLI), not automatic for all restaurants.
- Two Places paths exist: cached enrichment in `search` vs live search in `restaurants`; they do not share storage or the same env-key naming (`GOOGLE_PLACES_API_KEY` vs `GOOGLE_API_KEY` / `GOOGLE_MAPS_JS_KEY`).
