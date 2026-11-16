# Top Picks scoring algorithm

HealthyFoodsNYC ranks a small pool of recent grade-A restaurants and shows the
top three on the home page (first page; with a borough selected, picks come
from that borough). Scoring is rule-based in
`search/recommend.py` (`score_restaurant`). MenuStat linking and meal filters
live in `search/menustat.py`.

## Explore more order

Explore more uses the same DB-only score (no Google calls), best first, ties
shuffled daily. A place with no inspection in the last two years gets −2 (most
likely closed; new places dated 1900-01-01 are not penalized). For a logged-in
user, places they marked Not interested are left out, and a place gets +1 for
a cuisine they liked (Like, heart, or 4–5 stars) and +1 for a favorite food.

## Setup (candidate flow)

1. Take the 9 best places by the DB-only health score used by Explore more
   (latest grade A +2, healthy cuisine +1, fast food −2, no inspection in two
   years −2 since the place has likely closed, ...; no Google calls),
   restricted to places whose latest grade is A. Ties are shuffled with a daily
   seed (see "Daily rotation" below). Places the user marked not interested are
   skipped. (Before: the most recently inspected grade-A places, which says
   nothing about how healthy a place is.)
2. Top picks are places for a meal: coffee/tea, bakery/desserts, donuts, frozen
   desserts, bagels/pretzels, bottled beverages and nuts/confectionary are left
   out, plus coffee/dessert chains filed under another cuisine (e.g. some
   Starbucks are "American"). Juice/smoothie bars stay. Explore more still lists
   these places, scored −1 so they appear lower. Gyms and studios with a juice
   bar (names with the whole word FITNESS, GYM, YOGA or PILATES) are left out
   too.
3. Exclude cuisines that are risky for the user’s free-text allergies (via
   `diet_filters.risky_cuisines` after keyword → `nuts` / `shellfish` mapping).
4. For logged-in users with a profile, add up to 3 favorite-food matches and up
   to 3 same-borough-as-home places (15 candidates max).
5. Enrich with Google Places (rating, price, up to 5 reviews), DOHMH grade, and
   in-app ratings; optionally resolve MenuStat calories by **fuzzy name match**.
6. Score each candidate; show the top 3 (one per cuisine) with their reason tags.

Price is **not** part of the numeric score (Budget-friendly is a tag only).
BMI is never shown on the page; it only shifts weights.

## Components (0–1)

| Part | How it is computed |
|---|---|
| **Health** | Base 0.5 ± 0.2 cuisine ± 0.3 × (healthy − unhealthy review share) − 0.2 if fast-food chain; clipped to [0, 1]. |
| **Inspection grade** | A = 1.0, B = 0.5, C = 0, pending/missing = 0.3. The grade is the latest *graded* inspection's; a place never graded is unknown (0.3, no "Grade A" tag or reason), not A. |
| **Rating** | Bayesian blend of Google + in-app ratings toward prior 4.0 (pseudo-count 20), then map 3.0 → 0 … 5.0 → 1. |
| **Calories** (MenuStat only) | Median calories of *qualifying* meals → `(800 − median) / 600`, clipped to [0, 1] (200 kcal → 1.0, 800 → 0.0). |

### Qualifying MenuStat meals

- Categories: Entrees, Sandwiches, Salads, Burgers, Pizza, Soup
- Protein ≥ 15 g, not a kids’ meal, calories present
- Latest `year` for that MenuStat restaurant
- One row per `item_name` (lowest calories kept)
- Need at least **3** qualifying meals or the place is treated as unlinked

## Weights

Without MenuStat link:

| Mode | Health | Grade | Rating |
|---|---|---|---|
| Default | 50% | 25% | 25% |
| Health focus (BMI ≥ 25 or `weight-loss` goal) | 60% | 25% | 15% |

With MenuStat calorie score available, add a **10%** calorie weight and
**renormalize** the other three to sum to 90% (same proportions):

| Mode | Health | Grade | Rating | Calories |
|---|---|---|---|---|
| Default + calories | 45% | 22.5% | 22.5% | 10% |
| Health focus + calories | 54% | 22.5% | 13.5% | 10% |

Final numeric score:

```text
100 × (weighted sum of available components) + profile adjustments
```

## Profile adjustments (logged-in)

| Signal | Effect |
|---|---|
| Favorite foods (whole-word on cuisine/name) | +10, tag “Your favorite” |
| Disliked foods | −15 |
| Same ZIP or borough as home address | +5, tag “Nearby” |
| Health goals | Extra healthy-review keywords (e.g. muscle-gain → protein) |
| Allergies | Candidate exclusion only (not a score delta) |

Home ZIP/borough and allergies are parsed heuristically from free-text profile
fields (no structured ZIP field).

## Reason tags (every tag that applies, fixed order)

1. Your favorite  
2. Nearby  
3. Healthy reviews (≥2 healthy reviews and ≥40% of reviews)  
4. **Lower-calorie menu** (MenuStat linked and calorie component ≥ 0.6, i.e. median ≤ 440 kcal)  
5. Budget-friendly (Google price `$`)  
6. Top rated (50+ votes, blended ≥ 4.5)  
7. Grade A (Grade B / Grade C are shown too; the card has no other grade badge)  

"Similar pick" (hover: "Because you liked …") / "You liked this" goes before
all of these.

## AI health score (reviews + menus)

`python manage.py score_health` (run locally; `pip install -r requirements-ml.txt`)
reads each restaurant's saved Google reviews and, for MenuStat chains, its meal
names. A pre-trained sentence-embedding model (`all-MiniLM-L6-v2`, no training)
compares every sentence with short healthy / unhealthy example sentences:

- closer to a healthy example → sentence score near 1, closer to an unhealthy
  one → near 0; sentences about other things (service, parking) are skipped
- restaurant score = average sentence score, pulled toward 0.5 with 3 neutral
  "prior" sentences so one review can't decide everything

Scores are stored in `community.HealthScore`. In the health component they
replace the review keyword count: `+ 0.6 × (ai − 0.5)` (same ±0.3 range).
Restaurants without a stored score keep the keyword method. The server never
loads the model. The score breakdown shows "Health (AI)" when it was used.

## Why this pick (reason sentences)

`score_restaurant()` also returns `breakdown["reasons"]` (and `reason_text`,
joined with " · "): up to 3 short sentences for the parts that raised the score
the most compared with an average place (a 0.5 component, no bonuses).

| Part | Sentence | Points counted |
|---|---|---|
| AI review score | Reviews describe fresh, healthy food | health weight × AI effect |
| Keyword reviews | Reviews mention healthy dishes | health weight × keyword effect |
| Healthy cuisine | Healthy cuisine (Salads) | health weight × 0.2 |
| Rating | Highly rated (4.8★, 500 reviews) | rating weight × (rating − 0.5) |
| MenuStat calories | Lighter menu choices | calorie weight × (calories − 0.5) |
| Favorite food | Matches your favorite food (tacos) | +10 |
| Home | Near your home | +5 |
| Like | Similar to X, which you liked | like bonus |
| Grade A | NYC health grade A | only if fewer than 2 other reasons |

"Reviews describe fresh, healthy food" needs an AI score of 0.6+ and
"Highly rated" needs 4.5+ stars with 50+ votes (the Top rated bar), so a score
just above average never becomes a claim. Pushes under 1 point are skipped. Grade A is a fallback because every Top pick
shares it. Top picks carry the list as `pick["reasons"]`; showing it on the
card is a separate UI change.

## Reason paragraph (Gemini, optional)

The detail page shows one or two plain sentences written by Gemini above the
reason list. On a restaurant's first visit, if `GEMINI_API_KEY` is set, the
page sends Gemini the restaurant's name, cuisine and general reasons (only
facts we computed), stores the answer in `community.ReasonBlurb`, and shows
it; later visits read the stored text. The score itself does not change.

- No Google review text is sent: Google's Places terms bar building content
  from it. Reviews are covered by Google's own summary (below).
- Personal reasons (favorite food, home, likes) are never sent, because the
  paragraph is shared by every viewer. The prompt allows only the given facts.
- Each paragraph stores `model|PROMPT_VERSION`; one from an older prompt is
  rewritten on the next visit (or not shown when there is no key).
- No key, a timeout (12 s), or any error → the page shows the plain list.
  A quota error pauses calls for 10 minutes; a failed place is retried after
  10 minutes. Tests never call Gemini (`GEMINI_API_KEY` is blank under
  `manage.py test`).
- `python manage.py write_reasons` can fill many places ahead of time
  (`--limit`, `--refresh`, `--dry-run`, `--sleep`).
- Needs `GEMINI_API_KEY` in `.env` and `pip install -r requirements-ml.txt`.
  The server needs both too to write new ones; without them it only reads
  stored paragraphs. Free-tier keys have per-minute and per-day limits.

## Google review summary

Google data requests also ask for `reviewSummary`, Google's own AI summary
of a place's reviews (no extra Gemini call from us). It is kept in
`PlaceEnrichment.raw_json`; `PlaceEnrichment.review_summary` returns its text,
the required "Summarized with Gemini" disclosure, the reviews link, and the
report link. Places fetched before this change have no summary until their
Google data is refreshed, and Google does not have one for every place.

The detail page fetches and stores a restaurant's Google data on its first
visit when none is stored (`GOOGLE_AUTO_FETCH`, on except under
`manage.py test`, plus `GOOGLE_PLACES_API_KEY`): one Text Search request
that returns the place and all its details (also used by Refresh and
`enrich_places`), once per restaurant. A failed fetch is retried after
10 minutes; until then the page shows "No Google data" and the Refresh button.

## Review shown on the card

Only 4–5 star reviews are shown on a Top Picks card (the rating score still
uses every review). Among those, the card shows the one the health check counts
as healthy with the most healthy words (goal words included); ties keep Google's
relevance order. With no healthy review it falls back to the first 4–5 star
review; with no 4–5 star review the card shows no review.

## MenuStat matching

There is no shared ID between DOHMH `camis` and MenuStat `Restaurant_ID`.
We normalize names (casefold, strip punctuation/diacritics) and:

1. Prefer exact normalized equality against distinct `MenuItem.restaurant` values  
2. Else accept an unambiguous prefix match (e.g. `McDonald's #123` → `McDonald's`)  
3. Else accept an unambiguous contains match  

Ambiguous matches (multiple candidates) are rejected → no calorie term / no
detail-page menu.

Restaurant detail pages (`/restaurant/<camis>/`) show the top 5 lowest-calorie
qualifying meals when a match succeeds, with a disclaimer.

## Detail-page healthiness score

`/restaurant/<camis>/` also shows the **same composite score** under the address
(labeled “Healthiness score”), with a line-by-line calculation:

- Each weighted part: value (0–1) × weight % = points  
- Profile adjustments when logged in (favorite / disliked / nearby)  
- Total  

Inputs come from the latest inspection grade, cached Google enrichment (rating,
reviews, price) when present, in-app ratings, MenuStat calorie score when linked,
and the viewer’s profile for personalization. BMI is never displayed; health-focus
mode is noted only as “personalized weights.”  
`score_restaurant()` returns `(score, tags, breakdown)` for this UI.

## Daily rotation, diversity, and feedback

- **Daily rotation:** the candidates come from the top DB-score tier (about
  2,600 grade-A places with a healthy cuisine), shuffled with a seed of today's
  date (America/New_York) + user id + borough. Same day + same user = same picks;
  the next day brings a new set. Google calls stay at about 9.
- **Cuisine diversity:** the final 3 are taken by score, skipping a cuisine that
  is already chosen; skipped places refill the list if fewer than 3 remain.
- **Like / Not interested** (logged-in, buttons on each Top pick card; pressing
  again undoes). Stored in `community.RecommendationFeedback` with the name and
  cuisine copied at press time. Star ratings count too: 4–5 = like, 1–2 = not
  interested; a button press wins over a star rating for the same place.
  - Not interested: that place is never shown to that user again. Two or more
    of one cuisine → −5 for that cuisine.
  - Like: +3 per liked place with the same cuisine (max +9) and the tag
    "Similar pick" (shown first; the tooltip says "Because you liked <name>").
  - Only 1 of the 3 picks may win thanks to a like bonus; other liked places
    compete with their score minus the bonus.
  - Weights are unchanged, so health still dominates: +9 is less than the gap
    between a salad place and a fast-food chain.
- Users with no feedback get the normal score plus rotation and diversity.
- **Borough:** when a borough is selected, all candidates (daily sample,
  favorite extras) come from that borough and the title reads "Today's Top
  Picks in <Borough>". Home-borough extras apply only if the home borough is the
  selected one. The seed includes the borough, so each borough has its own set.

## Choices (why this design)

- Calories only when linked, so local restaurants without MenuStat still use the
  original three-part score.
- 10% calorie weight keeps the term informative without dominating health/grade.
- Renormalization keeps linked and unlinked scores on a similar 0–100 scale.
- Median of filtered meals avoids drink/topping zeros and one extreme item.
- Detail-page top-5 reuses the same filters for transparency.

## Concerns / limits

- **Coverage:** MenuStat is mostly national chains; only a small share of NYC
  inspected restaurants name-match. Linked places can look systematically
  different in the ranking.
- **Stale menus:** Historical MenuStat rows are often from **2017–2018** and may
  not match today’s menu. Disclaimers appear on the detail page and in the README.
- **Fuzzy matching:** Name match can mis-link similarly named chains, renames, or
  food-hall locations. Prefer a durable CAMIS↔MenuStat map later.
- **Overlap with fast-food penalty:** Many MenuStat hits are chains already
  penalized in the health component; calorie weight can reinforce that.
- **Keyword health:** Review health is word-count based, not semantic.
- **Google review sample:** At most five relevance-ordered Google reviews.
- **API cost:** Each Top Picks load may call Google for up to ~9–15 candidates
  (`POOL_SIZE` in `search/views.py`).

## Code map

| Module | Role |
|---|---|
| `search/recommend.py` | Pure scoring + tags |
| `search/menustat.py` | Match, qualifying meals, median, top-5 |
| `search/views.py` | `_top_picks`, `restaurant_detail` wiring |
| `search/test_recommend.py` / `search/test_menustat.py` | Unit coverage |
| `search/test_daily_feedback.py` | Rotation, diversity, Like / Not interested |
| `search/reason_writer.py` / `write_reasons` command | Gemini reason paragraph (local) |
| `search/test_reason_writer.py` | Prompt, cleanup, command (fake Gemini) |
