# Top Picks scoring algorithm (v4 / ranking-v2)

HealthyFoodsNYC ranks a small pool of recent grade-A restaurants and shows the
top three on the home page (first page; with a borough selected, picks come
from that borough). Scoring is rule-based in
`search/recommend.py` (`score_restaurant`). MenuStat linking and meal filters
live in `search/menustat.py`. Design rationale:
`md_guides/ranking-v2-plan.md`.

**Pipeline diagrams** (candidate pool → enrichment → formula → Top 3):
[`scoring-pipeline.md`](scoring-pipeline.md).

**Nutrition and safety are separate.** The detail page “Health estimate” is
menu calories (when linked) or a soft prior — not the inspection grade.
Grade is an **Inspection safety** term in the ranking blend and a badge/filter.

## One ranking for Top picks and Explore more

Each viewer gets one ranking per day (and per selected borough): the DB-only
score below plus their taste, ties shuffled with a seed made of the date, the
user ID and the borough. Explore more pages through this list; Top picks score
its first 25 places for a meal (see Setup). Explore more's first page is drawn
from those same places, so its Google lookups come from the cache: about 25
Google calls on a first load, none on a reload within the hour.

DB-only score (no Google calls): latest grade A +2 / B +1, healthy cuisine +1,
unhealthy or non-meal cuisine −1, fast food −2, no inspection in the last two
years −2 (most likely closed; new places dated 1900-01-01 are not penalized).
Taste, for a logged-in user: places they marked Not interested are left out.
Within one score, a place in a cuisine they liked (Like, heart, or 4–5 stars)
or matching a favorite food tends to come about 3x earlier (its shuffle number
is divided by 3), so it is mixed in rather than filling the top; taste never
lifts a place above a better score. Top picks candidates hold at most 5 places
of one cuisine.

## Setup (candidate flow)

1. Take the 25 best places for a meal in the viewer's ranking (the list
   Explore more shows; see above), by the DB-only health score
   (latest grade A +2, healthy cuisine +1, fast food −2, no inspection in two
   years −2 since the place has likely closed, ...; no Google calls),
   restricted to places whose latest grade is A. Ties are shuffled with a daily
   seed (see "Daily rotation" below). Places the user marked not interested are
   skipped.
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
   in-app ratings; optionally resolve MenuStat calories by **fuzzy name match**
   (with match kind + menu year for confidence).
6. Score each candidate; show the top 3 (one per cuisine). Ties prefer higher
   confidence, then rating.

Price is **not** part of the numeric score (Budget-friendly is a tag only).
BMI is never shown on the page; it only shifts weights slightly (health focus).

## Health estimate (detail headline)

```text
if MenuStat linked:
    health_estimate = 100 × menu_health
else:
    health_estimate = 100 × prior_health
```

Shown with **confidence** (high / medium / low). Profile adjustments are not
folded into this headline number; they appear under ranking adjustments.

### Menu health (0–1)

Median calories of *qualifying* meals → `(800 − median) / 600`, clipped to
[0, 1] (200 kcal → 1.0, 800 → 0.0).

### Prior health (0–1) — unlinked only

Base 0.5, then soft priors (capped):

| Signal | Effect |
|---|---|
| Healthy / unhealthy cuisine lists | ±0.1 |
| Review keyword share (healthy − unhealthy) | ×0.1 → ±0.1 |
| Known fast-food chain name | −0.15 |

### Confidence

| Level | When |
|---|---|
| **High** | Exact MenuStat name match, ≥5 qualifying meals, menu year ≥ 2019 |
| **Medium** | Prefix/contains match, or &lt;5 meals, or menu year &lt; 2019 |
| **Low** | No MenuStat link (prior only) |

## Ranking sort score (Top Picks)

```text
100 × (nutrition_or_prior × w_n + safety × w_s + rating × w_r)
  + profile / feedback / mood-energy adjustments
```

### Components (0–1)

| Part | How it is computed |
|---|---|
| **Nutrition** (linked) | `menu_health` from MenuStat median calories of qualifying meals. |
| **Prior / Health** (unlinked) | Soft prior: base 0.5 ± cuisine ± review share − fast-food penalty; clipped to [0, 1]. |
| **Inspection safety** | A = 1.0, B = 0.5, C = 0, pending/missing = 0.3. Latest *graded* inspection; never graded = unknown (0.3). |
| **Rating** | Bayesian blend of Google + in-app ratings toward prior 4.0 (pseudo-count 20), then map 3.0 → 0 … 5.0 → 1. |
| **Personal fit** | Favorite/disliked foods, goals, mild allergies, home area, Like / Not interested (when profile or feedback present). |

### Weights

| Mode | Nutrition / prior | Safety | Rating | Personal |
|---|---|---|---|---|
| Linked (default) | 70% menu | 20% | 10% | — |
| Linked + health focus | 75% menu | 15% | 10% | — |
| Unlinked (default) | 40% prior | 40% | 20% | — |
| Unlinked + health focus | 55% prior | 30% | 15% | — |
| Personal (profile/feedback) | share of remaining after personal 20% | | | 20% |

Health focus: BMI ≥ 25 or `weight-loss` goal. Mood/energy check-in adjusts the sort score separately.

### Qualifying MenuStat meals

- Categories: Entrees, Sandwiches, Salads, Burgers, Pizza, Soup
- Protein ≥ 15 g, not a kids’ meal, calories present
- Latest `year` for that MenuStat restaurant
- One row per `item_name` (lowest calories kept)
- Need at least **3** qualifying meals or the place is treated as unlinked

## Profile adjustments (logged-in)

| Signal | Effect |
|---|---|
| Favorite foods (whole-word on cuisine/name) | +10, tag “Your favorite” |
| Disliked foods | −15 |
| Same ZIP or borough as home address | +5, tag “Nearby” |
| Health goals | Extra healthy-review keywords (e.g. muscle-gain → protein) |
| Allergies | Candidate exclusion only (not a score delta) |
| Today's mood / energy (`MoodLog`) | See table below; tags “Fits your energy” / “Comfort for your mood” |

### Mood / energy adjustments (today's NY check-in only)

Strictness = average of mood and energy (1–5). A missing side counts as **3**
so a partial check-in still moves rankings. Implemented in `mood_overlay()`.

| Strictness | Effect |
|---|---|
| High (avg ≥ 4) | Global tilt `12 × (nutrition − 0.5)`; +8 light/healthy cuisines; −6 heavy/fast-food |
| Low (avg ≤ 2) | Laxer tilt `−6 × (nutrition − 0.5)`; +12 comfort cuisines; +8 hearty cuisines |
| Mid (~3) | No cuisine/nutrition overlay |

When a mood check-in exists, Claude “Picked for you” shortlists may still
supply reasons, but **final card order follows** `pick_top` / `score_restaurant`
(so mood/energy can change rankings). After check-in, the home page calls a
cheap rerank endpoint that reapplies `mood_overlay` on a cached base pool
(no Google / MenuStat / AI).

### Distance × energy (user pin)

When the viewer has a saved location pin (`UserProfile.location_lat/lng`) and a
mood check-in, and the restaurant has coordinates (Google enrichment), a
**distance adjustment** is added after mood:

| Energy | Curve (miles) |
|---|---|
| ≤ 2 | `12 × exp(−mi / 0.75) − 3` (clipped); tag “Closer for your energy” within 1 mi |
| 3 | `5 × exp(−mi / 1.2) − 1` |
| ≥ 4 | `3 × exp(−mi / 2.5)` (flatter — near and far stay closer in score) |

Missing pin, check-in, or place coords → no distance term.

Home ZIP/borough and allergies are parsed heuristically from free-text profile
fields (no structured ZIP field).

## Reason tags (every tag that applies, fixed order)

1. Your favorite  
2. Nearby  
3. **Menu-based estimate** (MenuStat linked)  
4. Healthy reviews (≥2 healthy reviews and ≥40% of reviews)  
5. **Lower-calorie menu** (MenuStat linked and menu health ≥ 0.6, i.e. median ≤ 440 kcal)  
6. Budget-friendly (Google price `$`)  
7. Top rated (50+ votes, blended ≥ 4.5)  
8. Grade A (Grade B / Grade C are shown too; the card has no other grade badge)  

"Similar pick" (hover: "Because you liked …") / "You liked this" goes before
all of these.

## AI health score (reviews + menus)

Each restaurant's Google reviews and, for MenuStat chains, its meal names are
read by a pre-trained sentence-embedding model (`all-MiniLM-L6-v2`, no
training), which compares every sentence with short healthy / unhealthy
example sentences:

- closer to a healthy example → sentence score near 1, closer to an unhealthy
  one → near 0; sentences about other things (service, parking) are skipped
- restaurant score = average sentence score, pulled toward 0.5 with 3 neutral
  "prior" sentences so one review can't decide everything

Scores are stored in `community.HealthScore`. In the health component they
replace the review keyword count: `+ 1.0 × (ai − 0.5)` (up to ±0.5; keywords
stay ±0.3). Real AI scores mostly fall between 0.3 and 0.8, so a factor of 0.6
moved the score too little; with 1.0 an AI score of 0.73 adds +0.23, and on
41 tested places the ranking followed the AI score without any place hitting
the 1.00 health cap.

When the score is worked out: the first time a place is shown (a Top picks
candidate, using the reviews Google just returned, or a detail page), with
`AI_LIVE_SCORING` on (always, except under `manage.py test`). The model runs
with fastembed (ONNX Runtime, from `requirements.txt`, about 90 MB downloaded
once to `FASTEMBED_CACHE_PATH` or the system temp folder), so the server runs
it too. `python manage.py score_health` can still fill many places ahead of
time (`--backend sentence-transformers` uses the PyTorch version).

Restaurants with no text about food health, or when the model can't load,
keep the keyword method. The breakdown says "Health (AI)" when AI was used.

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
detail-page menu. Match kind feeds confidence (`exact` vs `prefix`/`contains`).

Restaurant detail pages (`/restaurant/<camis>/`) show the top 5 lowest-calorie
qualifying meals when a match succeeds, with a disclaimer.

## Detail-page UI

`/restaurant/<camis>/` shows:

- **Health estimate** (nutrition/prior only) + confidence  
- Line-by-line **ranking** parts: nutrition/prior, inspection safety, rating  
- Profile adjustments when logged in  
- Ranking total (used for Top Picks ordering)

BMI is never displayed; health-focus mode is noted as “personalized weights.”  
`score_restaurant()` returns `(sort_score, tags, breakdown)` with
`health_estimate`, `confidence`, and labeled `parts`.

## Daily rotation, diversity, and feedback

- **Daily rotation:** the candidates come from the top DB-score tier (about
  2,600 grade-A places with a healthy cuisine), shuffled with a seed of today's
  date (America/New_York) + user id + borough. Same day + same user = same picks;
  the next day brings a new set. Google calls stay at about 9.
- **Cuisine diversity:** the final 3 are taken by score, skipping a cuisine that
  is already chosen; skipped places refill the list if fewer than 3 remain.
  Score ties prefer higher confidence, then Google rating.
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
- Users with no feedback get the normal score plus rotation and diversity.
- **Borough:** when a borough is selected, all candidates (daily sample,
  favorite extras) come from that borough and the title reads "Today's Top
  Picks in <Borough>". Home-borough extras apply only if the home borough is the
  selected one. The seed includes the borough, so each borough has its own set.
- **Mood / energy check-in** (logged-in, above Top Picks; also on `/profile/`):
  stored in `accounts.MoodLog` with one row per user per America/New_York day
  (re-submit updates today). Feeds the assistant and **Top Picks / detail
  ranking adjustments** (see mood table above). Plan:
  `md_guides/mood-energy-survey-plan.md`.

## Choices (why this design)

- Menu nutrition dominates when linked (70%); cuisine stereotypes are soft priors.
- Safety stays visible but is not confused with “healthy food.”
- Confidence keeps sparse/stale MenuStat from looking precise.
- Explore more keeps the cheap DB-only `explore_score` (no Google).
- Median of filtered meals avoids drink/topping zeros and one extreme item.

## Concerns / limits

- **Coverage:** MenuStat is mostly national chains; only a small share of NYC
  inspected restaurants name-match. Linked places can look systematically
  different in the ranking.
- **Stale menus:** Historical MenuStat rows are often from **2017–2018** →
  medium confidence + disclaimers.
- **Fuzzy matching:** Name match can mis-link similarly named chains, renames, or
  food-hall locations. Prefer a durable CAMIS↔MenuStat map later.
- **Keyword health:** Review prior is word-count based, not semantic (capped ±0.1).
- **Google review sample:** At most five relevance-ordered Google reviews.
- **API cost:** Each Top Picks load may call Google for up to ~9–15 candidates
  (`POOL_SIZE` in `search/views.py`).

## Code map

| Module | Role |
|---|---|
| `search/recommend.py` | Pure scoring + tags + confidence |
| `search/menustat.py` | Match kind, qualifying meals, median, nutrition link |
| `search/views.py` | `_top_picks`, `restaurant_detail` wiring |
| `search/test_recommend.py` / `search/test_menustat.py` | Unit coverage |
| `search/test_daily_feedback.py` | Rotation, diversity, Like / Not interested |
| `md_guides/scoring-pipeline.md` | End-to-end pipeline + mermaid diagrams |
| `md_guides/ranking-v2-plan.md` | Design plan / remaining phases |
| `search/reason_writer.py` / `write_reasons` command | Gemini reason paragraph (local) |
| `search/test_reason_writer.py` | Prompt, cleanup, command (fake Gemini) |
