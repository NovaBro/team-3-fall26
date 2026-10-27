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

- `/` — search restaurant inspections by name, borough, ZIP, grade, diet, or allergy.
- `/restaurant/<camis>/` — full inspection/violation history for one restaurant.
- `/explore/` — browse the other five datasets with text search and pagination.
- `/farmers-markets/` — map of NYC farmers markets.
- `/combined-map/` — Google Map of farmers markets, Shop Healthy stores, DOHMH
  restaurants with saved Places enrichment, and (on demand) live Google
  restaurants. Needs `GOOGLE_MAPS_JS_KEY`; live Google layer also needs
  `GOOGLE_API_KEY` and is off until you load it.
- `/restaurants/` — find restaurants by area, price range, diet, allergy, cuisine,
  minimum rating, open now, and walking distance
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

## Diet and allergy filters

Both searches share one set of definitions in `restaurants/diet_filters.py`. Each
diet or allergy is a single entry there; the dropdowns and checkboxes on both pages
are built from it, so adding one (e.g. gluten-free) needs no template changes.

Diets match restaurants that **specialize** in them, not places with one matching dish:

| Diet | Homepage (`/`, NYC cuisine) | `/restaurants/` (Google Places) |
|---|---|---|
| Vegetarian | Vegetarian, Vegan | Google's `servesVegetarianFood` |
| Vegan | Vegan | `vegan_restaurant` place type |
| Pescatarian | Seafood, Vegetarian, Vegan | `seafood_restaurant` place type |
| Keto | Steakhouse, Barbecue, Seafood | "keto-friendly restaurants" text search |
| Halal | not available (no NYC cuisine category) | `halal_restaurant` place type |
| Kosher | Jewish/Kosher | not available (no Google place type) |

Keto is approximate: no data source labels restaurants as keto.

Allergy filters ("Avoid nut-heavy cuisines", "Avoid shellfish-heavy cuisines") skip
restaurants whose cuisine or Google place type commonly uses the allergen. On the
Google page they check every place type, not just the main one. **No data source
lists what is in a restaurant's food**, so these filters can't promise a place is
safe. The results always show a note telling users to confirm allergies with the
restaurant. Restaurants with no cuisine listed are kept.

The cuisine and place-type lists are a best guess; review them in
`restaurants/diet_filters.py`. `/restaurants/` also filters by cuisine name, minimum
star rating, and whether the place is open now.

## Data

The SQLite database (`database/nyc_food.db`) is generated, not committed. Rebuild it
any time with `import_datasets`; the command is idempotent.

| Dataset | Imported as |
|---|---|
| `restaurant_data_set_2_*.csv` | `RestaurantInspection` |
| `restaurant_cuisines_*.csv` | `RestaurantInspection.cuisine` (matched on CAMIS) |
| `DOHMH_MenuStat_(Historical)_*.csv` | `MenuItem` |
| `Good_Food_Purchasing_Data_*.csv` | `AgencyPurchase` |
| `NYC_Farmers_Markets_*.csv` | `FarmersMarket` |
| `Recognized_Shop_Healthy_Stores_*.csv` | `HealthyStore` |
| `DPR_Eateries_001.json` | `ParkEatery` |

`restaurant_cuisines_*.csv` is a small CAMIS → cuisine lookup from NYC Open Data
("DOHMH New York City Restaurant Inspection Results", dataset `43nn-pn8j`). It is kept
separate because the full export is too large for GitHub. To refresh it:

```bash
curl -G -o database/datasets/restaurant_cuisines_$(date +%Y%m%d).csv \
  "https://data.cityofnewyork.us/resource/43nn-pn8j.csv" \
  --data-urlencode '$select=camis,cuisine_description' \
  --data-urlencode '$group=camis,cuisine_description' \
  --data-urlencode '$limit=100000'
```

After pulling changes to the models or datasets, rebuild your local database:

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_datasets
```

## Tests

```bash
.venv/bin/python manage.py test
```
