# Team Project repo

| Branch | Build | Coverage |
|---|---|---|
| develop | [![CI develop](https://github.com/gcivil-nyu-org/team-3-fall26/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/gcivil-nyu-org/team-3-fall26/actions/workflows/ci.yml?query=branch%3Adevelop) | [![Coverage develop](https://coveralls.io/repos/github/gcivil-nyu-org/team-3-fall26/badge.svg?branch=develop)](https://coveralls.io/github/gcivil-nyu-org/team-3-fall26?branch=develop) |
| main | [![CI main](https://github.com/gcivil-nyu-org/team-3-fall26/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/gcivil-nyu-org/team-3-fall26/actions/workflows/ci.yml?query=branch%3Amain) | [![Coverage main](https://coveralls.io/repos/github/gcivil-nyu-org/team-3-fall26/badge.svg?branch=main)](https://coveralls.io/github/gcivil-nyu-org/team-3-fall26?branch=main) |

NYC food / open-data search project. Raw datasets live in `database/datasets/`.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_datasets   # loads CSVs/JSON into database/nyc_food.db
.venv/bin/python manage.py runserver
```

Then open http://127.0.0.1:8000/.

## Web interface

- `/` — **Find food**: farmers markets, Shop Healthy grocery stores, and
  restaurants on one map (MapLibre) with a shared filter sidebar: store type,
  name, borough, ZIP, distance from your location, market day, and restaurant
  filters (cuisine, inspection grade, diet, allergies). Restaurant results come
  from NYC inspection records by default, or live from Google Places, which
  adds price, minimum rating, and open-now filters. Clicking a pin or result
  opens community ratings, comments, and photos.
- `/home/` — card view of NYC restaurants, filterable by borough, with a Google Places lookup on each card and scored **Today's Top Picks** on page 1 (see [`md_guides/scoring-algorithm.md`](md_guides/scoring-algorithm.md)).
- `/restaurant/<camis>/` — full inspection/violation history for one restaurant; when MenuStat name-matches, a top-5 lower-calorie meal table.
- The old `/restaurants/`, `/combined-map/`, `/farmers-markets/`, and `/explore/`
  tabs were merged into `/` (issue #109) and now redirect there.

### Missing locations

Inspection records have no coordinates, and a few markets and stores don't
either. For the rows on the page you're viewing, Find food asks Google Places
Text Search (needs `GOOGLE_API_KEY`) and stores the answer in
`community.LocationLookup`. Misses are stored too, and entries expire after 30
days (Google's limit for caching coordinates). Backfill in bulk with:

```bash
.venv/bin/python manage.py locate_places                    # markets + grocery
.venv/bin/python manage.py locate_places --type restaurant --limit 200
```

## Google Places restaurant results

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
or seed in bulk. Enrichment is stored by pin `(kind, key)` for DOHMH restaurants,
farmers markets, and Shop Healthy stores:

```bash
export GOOGLE_PLACES_API_KEY="your-key"
# Markets + stores first (fits free monthly caps), then capped restaurants:
.venv/bin/python manage.py enrich_places --type farmers_market --type grocery --sleep 0.5
.venv/bin/python manage.py enrich_places --type restaurant --limit 4000 --sleep 0.5
```

`enrich_places` skips pins that already have stored data; pass `--refresh` to
overwrite. Restaurant targets prefer CAMIS that still lack coordinates. Each
place costs two API calls (Text Search + Place Details); results go to
`PlaceEnrichment`/`PlaceReview` in `community.db` and show in the Find food
Reviews panel.

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

**MenuStat caveats:** menus are historical (often **2017–2018**) and may not match
today’s offerings. Linking inspections to MenuStat is **fuzzy name match**, not
CAMIS — there is no shared restaurant ID across the two datasets. Wrong or missing
links are possible (renames, food halls, similar chain names). When a match has
enough qualifying meals, Top Picks may use a 10% calorie weight and the detail
page may show a top-5 lower-calorie menu. Full rules:
[`md_guides/scoring-algorithm.md`](md_guides/scoring-algorithm.md).

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

## CI/CD

`.github/workflows/ci.yml` runs one `test` job (black, flake8, unit tests under coverage, Coveralls upload) on:

- pull requests into `develop` or `main` (pre-submit)
- pushes to `develop` or `main`
- a daily schedule at 09:00 UTC, which tests `main` (post-submit)
- manual runs from the Actions tab

After `test` passes, a push to `develop` or a same-repo pull request into `develop` deploys to `Nycfood-env` (integration). A push to `main` deploys to `Nycfood-env-main` (production). Deploys only run on `gcivil-nyu-org/team-3-fall26`; fork pull requests and production stay out of the PR path. Integration deploys share one concurrency group, so overlapping runs queue; whichever finishes last is what stays live (including an older commit).

Scheduled runs use the copy of `ci.yml` on the default branch, `develop`. Change CI on `develop` first, then merge `develop` into `main`, so both branches keep the same workflow and README badges.

Repository settings that the workflow depends on:

- Branch protection on `develop` and `main` with "Require status checks to pass before merging" and the `test` check required.
- `gcivil-nyu-org/team-3-fall26` enabled on coveralls.io.
- The trust policy of the IAM role `github-nycfood-deploy` allows `repo:gcivil-nyu-org/team-3-fall26:ref:refs/heads/develop`, `repo:gcivil-nyu-org/team-3-fall26:ref:refs/heads/main`, and `repo:gcivil-nyu-org/team-3-fall26:pull_request`, and the role may update both Elastic Beanstalk environments.

## Elastic Beanstalk

The integration site is http://Nycfood-env.eba-jht3rtv2.us-east-1.elasticbeanstalk.com. The Elastic Beanstalk application is `nycfood`, the environments are `Nycfood-env` (integration, from `develop`) and `Nycfood-env-main` (production, from `main`), and the region is `us-east-1`. GitHub Actions deploys with `eb deploy` after tests pass (see [CI/CD](#cicd)). The workflow assumes the IAM role `github-nycfood-deploy`; no AWS keys are stored in GitHub.

The instance downloads `database/nyc_food.db` and `database/community.db` from `elasticbeanstalk-us-east-1-322134621417` before migrate. Those files are not in Git and are not in the deploy bundle. Django still opens them as local SQLite files. Rows written on the live site, and files in `media/`, are replaced by the next deploy. To change the canonical databases, upload them again:

```bash
aws s3 cp database/nyc_food.db s3://elasticbeanstalk-us-east-1-322134621417/nyc_food.db
aws s3 cp database/community.db s3://elasticbeanstalk-us-east-1-322134621417/community.db
```

Before the first Actions deploy, upload both files and attach `deploy/s3-db-read-policy.json` to the instance role `aws-elasticbeanstalk-ec2-role` (so it can `GetObject` those keys). A failed download fails the deploy. API keys come from SSM Parameter Store.

If the deploy fails, run `eb logs Nycfood-env` and read `eb-engine.log` and `web.stdout.log`.

More detail: [md_guides/deploy_workflow.md](md_guides/deploy_workflow.md) (checklist and team rules) and [md_guides/aws_deployment.md](md_guides/aws_deployment.md) (IAM, SSM, and troubleshooting).
