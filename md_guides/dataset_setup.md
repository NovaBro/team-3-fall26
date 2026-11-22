# Dataset setup and website usage

Two sources feed the site:

- **NYC Open Data** files in `database/datasets/`, bulk-loaded into SQLite by
  `import_datasets`: MenuStat chain menus, farmers markets and Shop Healthy
  stores.
- **Google Places**: every restaurant. They are stored in `community.Restaurant`
  (keyed by Google place id) and kept fresh by `sync_restaurants`.

Filename suffix `YYYYMMDD` (e.g. `20261011`) is the **download date**, not a content/coverage date. Dataset contents may reference older periods (e.g. 2017–2026).

## Databases

| File | Alias | Holds |
|------|-------|-------|
| `database/nyc_food.db` | `default` | Open Data tables below; rebuilt by `import_datasets` |
| `database/community.db` | `community` | Google restaurants (`Restaurant`), Google details and reviews (`PlaceEnrichment`, `PlaceReview`), ratings, comments, photos, likes, AI scores |
| `database/users.db` | `users` | Accounts, profiles, mood logs, sessions |

Routers: `nycfood/routers.py` (users) and `community/router.py`. None of the
files are committed.

## Datasets on disk

| File | Approx. size | Rows | Role | Key fields |
|------|--------------|------|------|------------|
| `DOHMH_MenuStat_(Historical)_*.csv` | ~21M | ~65K | Chain menu nutrition (MenuStat) | `Restaurant_ID`, `Menu_Item_ID`, nutrients per serving / per 100g, kids/LTO flags |
| `NYC_Farmers_Markets_*.csv` | ~300K | ~2.3K | Farmers markets | name, borough, lat/long, hours, season, EBT |
| `Recognized_Shop_Healthy_Stores_*.csv` | ~104K | 712 | Shop Healthy stores | store, address, lat/long, program wave, geo IDs |

Total: about 22 MB / 68K rows.

Dropped: the DOHMH restaurant inspection results (and its CAMIS → cuisine
lookup), Good Food Purchasing and DPR park eateries. Restaurants come from
Google; nothing read the other two after issue #109.

There is **no shared key** between MenuStat `Restaurant_ID` and Google place
ids. A restaurant is linked to MenuStat by fuzzy name match
(`search/menustat.py`).

## Import / ETL

Rebuild the dataset database anytime:

```bash
.venv/bin/python manage.py import_datasets
```

Implemented in `search/management/commands/import_datasets.py`. The command is
idempotent and never touches `community.db` or `users.db`.

### Flow

1. Resolve the latest file matching each glob under `database/datasets/`
2. Delete all rows in the target model (full reload)
3. Read CSV via pandas; normalize text, zip codes, numbers and booleans
4. `bulk_create` in batches of 2000 into `database/nyc_food.db`

### Source → Django model

| Dataset | Model (`search/models.py`) |
|---------|----------------------------|
| `DOHMH_MenuStat_(Historical)_*.csv` | `MenuItem` |
| `NYC_Farmers_Markets_*.csv` | `FarmersMarket` |
| `Recognized_Shop_Healthy_Stores_*.csv` | `HealthyStore` |

**Partial MenuStat import:** most `*_100g` nutrients (except `Calories_100g`), serving-size helper columns, and `*_text` nutrient columns are dropped at import time.

## Restaurants (Google Places)

`community.Restaurant` holds one row per place: name, address, street, ZIP,
borough, cuisine, primary type, coordinates, rating and review count, price
level, business status, Maps link, photo name, and a `shuffle_seed` used to
rotate rankings in SQL. Its Google details and up to 5 reviews are in
`PlaceEnrichment` / `PlaceReview` (kind `restaurant_google`, key
`google:<place_id>`); ratings, comments and photos hang off the same key.

- **Cuisine** comes from Google place types (`restaurants/cuisines.py`), mapped
  onto the labels the ranking code uses ("Chinese", "Coffee/Tea", "Juice,
  Smoothies, Fruit Salads", ...). Generic types ("restaurant") never overwrite a
  stored cuisine.
- **Borough** comes from the address components, else the ZIP code
  (`restaurants/boroughs.py`). Places outside the five boroughs are skipped.
- **Writes:** `search/services/places.py` (`enrich_place_id`,
  `save_restaurant`). The detail page fetches a place the first time it is
  opened (so live Find food results become saved restaurants), and
  **Refresh Google data** re-fetches it.

### `sync_restaurants`

```bash
.venv/bin/python manage.py sync_restaurants --dry-run
.venv/bin/python manage.py sync_restaurants --limit 200 --sleep 0.2
```

- **Refresh:** places older than `--max-age-days` (30) get one Place Details
  call each (details and reviews).
- **Discover:** a Text Search per borough × term (`DISCOVERY_TERMS`), up to
  `--pages` pages of 20 results, restricted to restaurants in the NYC box.
- `--limit` caps Google requests per run. `--boro`, `--term`, `--place-id`,
  `--refresh-only` and `--discover-only` narrow a run.

Storing Google data beyond place ids goes against Google's terms; the project
accepts this and refreshes rows within 30 days.

### Upgrade from inspection records

`community/migrations/0011_google_restaurants.py` (code in
`community/dohmh_conversion.py`) re-keyed every restaurant row from CAMIS to
its Google place id and created a `Restaurant` for each place that had Google
data, taking cuisine and borough from the inspection summary. It must run
before `search/0008`, which deletes the inspection tables, so migrate the
`community` database first.

## How the website uses the data

| Path | Behavior |
|------|----------|
| `/` (Find food) | Farmers markets (latest year), Shop Healthy stores and saved restaurants on one map and list; or live Google results for restaurants |
| `/home/` | Top picks and Explore more, ranked from saved restaurants with no Google calls (except a photo-only lookup for a shown Top pick with no stored photo) |
| `/restaurant/<place_id>/` | Score breakdown, Menu box, lower-calorie MenuStat items |
| `POST /restaurant/<place_id>/refresh-google/` | Re-fetch the place from Google |

Markets and stores without coordinates are located through
`community.LocationLookup`, then a Google Text Search for the visible page
(`search/locations.py`); `locate_places` backfills them. Restaurants always
have coordinates.

MenuStat is not listed on its own, but it feeds Top Picks ranking, health-goal
fit, the "what to order" menu box, and lower-calorie items on restaurant detail
pages (`search/recommend.py`, `search/goal_fit.py`, `search/what_to_order.py`).

Farmers markets and Shop Healthy stores get Google details with
`enrich_places --type farmers_market --type grocery`.

## Data flow

```
database/datasets/*.csv
        │
        ▼
  import_datasets  ──►  nyc_food.db (MenuItem, FarmersMarket, HealthyStore)

Google Places API
        │
        ├── sync_restaurants / detail page ──► community.Restaurant
        │                                      + PlaceEnrichment, PlaceReview
        ├── Find food "Google Places (live)" (request time; stored when opened)
        └── missing market/store locations ──► LocationLookup (30-day cache)

curate_pool (after import_datasets / sync_restaurants)
        │  top 500 per borough per category by weighted Google rating
        ▼
Model.pool (active rows) ──► /home/ Top picks + Explore more, Find food, assistant
```

How the pool is chosen and how restaurants are scored from it:
[`scoring-pipeline.md`](scoring-pipeline.md).

## Setup reminder

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate --database=community
.venv/bin/python manage.py migrate --database=users
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_datasets
.venv/bin/python manage.py sync_restaurants --limit 200
.venv/bin/python manage.py runserver
```

Open http://127.0.0.1:8000/.

## Gaps and caveats

- No ID-based joins: restaurants link to MenuStat only by fuzzy name match, so links can be wrong or missing.
- MenuStat is only partially imported (many CSV columns dropped).
- The pool is only as complete as discovery: places no query surfaced are missing until someone opens them from a live search.
- No food-safety signal: inspection grades are gone, so scores use nutrition and ratings only.
- Two key names exist: `GOOGLE_PLACES_API_KEY` (stored data) vs `GOOGLE_API_KEY` (live search, photos).
