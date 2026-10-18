# Team Project repo

NYC food / open-data search project. Raw datasets live in `database/datasets/`.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_datasets   # loads CSVs/JSON into database/nyc_food.db
.venv/bin/python manage.py runserver
```

Then open http://127.0.0.1:8000/.

## Web interface

- `/` — search restaurant inspections by name, borough, ZIP, or grade.
- `/restaurant/<camis>/` — full inspection/violation history for one restaurant.
- `/explore/` — browse the other five datasets with text search and pagination.
- `/restaurants/` — find restaurants by area, price range, diet, and walking distance
  from your location (live Google Places data; see below).

## Restaurant filters (`/restaurants/`)

Needs a Google API key with **Places API (New)** enabled (and billing on the Google
Cloud project). Copy `.env.example` to `.env` and fill in `GOOGLE_API_KEY`; add
`GOOGLE_MAPS_JS_KEY` (Maps JavaScript API) to also show the results map. Never commit `.env`.

- Searches are limited to NYC unless you use "Use my location".
- Distance filters need "Use my location"; results are then sorted by distance.
- Invalid filter values (e.g. `?price=cheap`) show an error instead of searching.
- Results come from Google at request time and are not stored (Google's terms
  restrict caching Places data). Each search is one billable Text Search request.

## Google Places enrichment

Set a Google Maps Platform API key (with the **Places API (New)** enabled) as an
environment variable, then either click **Get Google data** on a restaurant page
or seed in bulk:

```bash
export GOOGLE_PLACES_API_KEY="your-key"
.venv/bin/python manage.py enrich_places --limit 25 --sleep 0.5
```

`enrich_places` skips restaurants that already have stored data; pass
`--refresh` to overwrite. Each restaurant costs two API calls (Text Search +
Place Details) and the result is stored in the `PlaceEnrichment`/`PlaceReview`
tables. Ratings, price level, location, website, and reviews are then served
from the local database without further API calls.

## Data

The SQLite database (`database/nyc_food.db`) is generated, not committed. Rebuild it
any time with `import_datasets`; the command is idempotent.

| Dataset | Imported as |
|---|---|
| `restaurant_data_set_2_*.csv` | `RestaurantInspection` |
| `DOHMH_MenuStat_(Historical)_*.csv` | `MenuItem` |
| `Good_Food_Purchasing_Data_*.csv` | `AgencyPurchase` |
| `NYC_Farmers_Markets_*.csv` | `FarmersMarket` |
| `Recognized_Shop_Healthy_Stores_*.csv` | `HealthyStore` |
| `DPR_Eateries_001.json` | `ParkEatery` |

## Tests

```bash
.venv/bin/python manage.py test
```
