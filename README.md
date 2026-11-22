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
.venv/bin/python manage.py migrate --database=community   # community.db (first)
.venv/bin/python manage.py migrate --database=users       # accounts: users.db
.venv/bin/python manage.py migrate                        # datasets: nyc_food.db
.venv/bin/python manage.py import_datasets   # loads CSVs into database/nyc_food.db
.venv/bin/python manage.py sync_restaurants --limit 200   # Google restaurants
.venv/bin/python manage.py runserver
```

Then open http://127.0.0.1:8000/.

## Web interface

- `/` — **Find food**: farmers markets, Shop Healthy grocery stores, and
  restaurants on one map (MapLibre) with a shared filter sidebar: store type,
  name, borough, ZIP, distance from your location, market day, and restaurant
  filters (cuisine, diet, allergies, price, minimum rating). Restaurant results
  come from the saved Google restaurants by default, or live from Google
  Places, which adds an open-now filter. Clicking a pin or result
  opens community ratings, comments, and photos.
- `/home/` — card view of NYC restaurants, filterable by borough, from the saved Google data (no API calls per card) and scored **Today's Top Picks** on page 1 (pipeline diagrams: [`md_guides/scoring-pipeline.md`](md_guides/scoring-pipeline.md); full rules: [`md_guides/scoring-algorithm.md`](md_guides/scoring-algorithm.md)).
- `/restaurant/<place_id>/` — one restaurant by Google place id: score breakdown and Menu box; when MenuStat name-matches, a top-5 lower-calorie meal table. A place found live on Google is stored the first time it is opened.
- The old `/restaurants/`, `/combined-map/`, `/farmers-markets/`, and `/explore/`
  tabs were merged into `/` (issue #109) and now redirect there.
- `/admin-dashboard/` — superuser-only platform overview, searchable accounts,
  account activity counts, and community comments. Account details omit private
  health-profile fields.
- `/admin/` — Django admin for staff, including the read-only user list. Grant
  `auth.view_user` only to staff who need to search and view accounts.

### Missing locations

Restaurants come from Google with coordinates, but a few markets and stores
have none. For the rows on the page you're viewing, Find food asks Google Places
Text Search (needs `GOOGLE_API_KEY`) and stores the answer in
`community.LocationLookup`. Misses are stored too, and entries expire after 30
days (Google's limit for caching coordinates). Backfill in bulk with:

```bash
.venv/bin/python manage.py locate_places                    # markets + grocery
.venv/bin/python manage.py locate_places --type grocery --limit 200
```

## Google Places restaurant results

Needs a Google API key with **Places API (New)** enabled (and billing on the Google
Cloud project). Copy `.env.example` to `.env` and fill in `GOOGLE_API_KEY`; add
`GOOGLE_MAPS_JS_KEY` (Maps JavaScript API) to also show the results map. Never commit `.env`.

- Searches are limited to NYC unless you use "Use my location".
- Distance filters need "Use my location"; results are then sorted by distance.
- Invalid filter values (e.g. `?price=cheap`) show an error instead of searching.
- Live results come from Google at request time. Each search is one billable
  Text Search request. Opening a result stores it as a saved restaurant.

## Restaurants (Google Places)

Restaurants come only from Google Places. They are stored in
`community.Restaurant` (keyed by Google place id) in `community.db`, with their
details and reviews in `PlaceEnrichment`/`PlaceReview` (kind
`restaurant_google`, key `google:<place_id>`). Top picks, Explore more, Find
food and the assistant rank this stored pool, so page views make no Google
calls. Cuisine labels come from Google place types
(`restaurants/cuisines.py`), borough from the address.

`sync_restaurants` keeps the pool filled (needs `GOOGLE_PLACES_API_KEY`):

```bash
export GOOGLE_PLACES_API_KEY="your-key"
.venv/bin/python manage.py sync_restaurants --dry-run          # show the plan
.venv/bin/python manage.py sync_restaurants --limit 200 --sleep 0.2
.venv/bin/python manage.py sync_restaurants --refresh-only     # re-fetch >30 days
.venv/bin/python manage.py sync_restaurants --discover-only --boro Queens
```

Refresh re-fetches places older than `--max-age-days` (30, Google's limit for
caching coordinates) with one Place Details call each; discovery runs a Text
Search per borough × cuisine term (up to `--pages` pages of 20). `--limit` caps
the total number of Google requests per run. Storing Google data beyond place
ids goes against Google's terms; this class project accepts that and keeps the
rows refreshed.

Farmers markets and Shop Healthy stores are enriched separately:

```bash
.venv/bin/python manage.py enrich_places --type farmers_market --type grocery --sleep 0.5
```

`enrich_places` skips pins that already have stored data; pass `--refresh` to
overwrite. Each place is one Text Search request.

### Menu (detail page)

The restaurant page loads a Menu box after the page itself
(`/restaurant/<place_id>/what-to-order/`). The menu comes from MenuStat for
chains; otherwise up to 10 Google photos are downloaded and one Gemini call
(`GEMINI_API_KEY`) reads the items on the menu photos. Items are shown grouped
into food, drinks and desserts. Menus read from Google photos are never
stored. Cost per page view without a MenuStat match: one Place Details
(photos) call, up to 10 photo calls, and one small Gemini call. Dish scoring
and picks (`score_dishes`, `pick` in `search/what_to_order.py`) are written but
not shown yet.

### Known limitation: stored Google data

Google's Places terms only allow storing place IDs. This class project still
stores Places data (ratings, reviews) in `PlaceEnrichment`/`PlaceReview`,
because the AI health score is computed from the reviews. A production
version would keep only place IDs and fetch the rest when needed. The
restaurant page no longer shows a Google data panel (rating, reviews).

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

Three SQLite files live in `database/`; none are committed.

| File | Holds | Rebuild |
|---|---|---|
| `nyc_food.db` (`default`) | Open Data tables below | `import_datasets` (idempotent) |
| `community.db` (`community`) | Google enrichment, ratings, comments, photos, scores | Not rebuildable; back it up |
| `users.db` (`users`) | Accounts, profiles, mood logs, sessions, admin log | Not rebuildable; back it up |

Routers (`nycfood/routers.py`, `community/router.py`) pick the file per app.
Community rows store a plain `user_id` that matches `users.db`.

Upgrading a checkout from before the split (accounts were in `nyc_food.db`):

```bash
.venv/bin/python manage.py migrate --database=users
.venv/bin/python manage.py move_accounts_db   # copies users, keeping their ids
```

| Dataset | Size | Rows | Imported as |
|---|---|---|---|
| `DOHMH_MenuStat_(Historical)_*.csv` | ~21 MB | ~65K | `MenuItem` |
| `NYC_Farmers_Markets_*.csv` | ~300 KB | ~2.3K | `FarmersMarket` |
| `Recognized_Shop_Healthy_Stores_*.csv` | ~104 KB | 712 | `HealthyStore` |

Total is about 22 MB / 68K rows. The `YYYYMMDD` filename suffix is the
download date, not the period the data covers. The DOHMH restaurant inspection
data, Good Food Purchasing and DPR park eateries datasets were dropped:
restaurants now come from Google Places.

**MenuStat caveats:** menus are historical (often **2017–2018**) and may not match
today’s offerings. Linking a Google restaurant to MenuStat is a **fuzzy name
match** — there is no shared restaurant ID. Wrong or missing
links are possible (renames, food halls, similar chain names). When a match has
enough qualifying meals, Top Picks may use menu nutrition as the dominant
weight and the detail page may show a top-5 lower-calorie menu. Pipeline
diagrams: [`md_guides/scoring-pipeline.md`](md_guides/scoring-pipeline.md).
Full rules: [`md_guides/scoring-algorithm.md`](md_guides/scoring-algorithm.md).

After pulling changes to the models or datasets, migrate (community first) and
reload the datasets:

```bash
.venv/bin/python manage.py migrate --database=community
.venv/bin/python manage.py migrate --database=users
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_datasets
```

### Upgrading from inspection-based restaurants

`community/0011` re-keys every restaurant row from its NYC inspection id
(CAMIS) to its Google place id: Google data, pins with their ratings, comments
and photos, likes, health scores, reason paragraphs and estimated menus. Each
restaurant that already had Google data becomes a saved restaurant, taking its
cuisine and borough from the inspection summary. That summary is deleted by
`search/0008`, so migrate `community` **before** the default database. Rows
whose restaurant was never matched to Google are dropped. Afterwards run
`sync_restaurants --refresh-only` to fill in Google place types, photos and
fresh ratings. `nyc_food_lite.db` is no longer used and can be deleted.

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

The instance downloads `database/nyc_food.db`, `database/community.db` and `database/users.db` from `elasticbeanstalk-us-east-1-322134621417` before migrate. Those files are not in Git and are not in the deploy bundle. Django still opens them as local SQLite files. Rows written on the live site, and files in `media/`, are replaced by the next deploy. To change the canonical databases, upload them again:

```bash
aws s3 cp database/nyc_food.db s3://elasticbeanstalk-us-east-1-322134621417/nyc_food.db
aws s3 cp database/community.db s3://elasticbeanstalk-us-east-1-322134621417/community.db
aws s3 cp database/users.db s3://elasticbeanstalk-us-east-1-322134621417/users.db
```

`users.db` may be missing from S3: the download is allowed to fail, `migrate --database=users` creates it, and `move_accounts_db` copies accounts out of `nyc_food.db` while `users.db` has none.

Before the first Actions deploy, upload both files and attach `deploy/s3-db-read-policy.json` to the instance role `aws-elasticbeanstalk-ec2-role` (so it can `GetObject` those keys). A failed download fails the deploy. API keys come from SSM Parameter Store.

If the deploy fails, run `eb logs Nycfood-env` and read `eb-engine.log` and `web.stdout.log`.

More detail: [md_guides/deploy_workflow.md](md_guides/deploy_workflow.md) (checklist and team rules) and [md_guides/aws_deployment.md](md_guides/aws_deployment.md) (IAM, SSM, and troubleshooting).

## AI assistant

The "Ask AI" chat and personalized Top Picks need `ANTHROPIC_API_KEY` in `.env` and stay off without it. See [md_guides/assistant.md](md_guides/assistant.md).
