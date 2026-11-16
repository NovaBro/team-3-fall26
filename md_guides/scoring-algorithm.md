# Top Picks scoring algorithm (v4 / ranking-v2)

HealthyFoodsNYC ranks a small pool of recent grade-A restaurants and shows the
top three on the home page (first page; with a borough selected, picks come
from that borough). Scoring is rule-based in
`search/recommend.py` (`score_restaurant`). MenuStat linking and meal filters
live in `search/menustat.py`. Design rationale:
`md_guides/ranking-v2-plan.md`.

**Nutrition and safety are separate.** The detail page “Health estimate” is
menu calories (when linked) or a soft prior — not the inspection grade.
Grade is an **Inspection safety** term in the ranking blend and a badge/filter.

## Setup (candidate flow)

1. Take the 9 best places by the DB-only explore score used by Explore more
   (latest grade A +2, healthy cuisine +1, fast food −2, ...; no Google calls),
   restricted to places whose latest grade is A. Ties are shuffled with a daily
   seed (see "Daily rotation" below). Places the user marked not interested are
   skipped.
2. Top picks are places for a meal: coffee/tea, bakery/desserts, donuts, frozen
   desserts, bagels/pretzels, bottled beverages and nuts/confectionary are left
   out, plus coffee/dessert chains filed under another cuisine (e.g. some
   Starbucks are "American"). Juice/smoothie bars stay. Explore more still lists
   these places, scored −1 so they appear lower.
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
| **Nutrition** (linked) | `menu_health` from MenuStat median calories |
| **Prior** (unlinked) | Soft prior above |
| **Inspection safety** | A = 1.0, B = 0.5, C = 0, pending/missing = 0.3 |
| **Rating** | Bayesian blend of Google + in-app ratings toward prior 4.0 (pseudo-count 20), then map 3.0 → 0 … 5.0 → 1 |

### Weights

| Mode | Nutrition / prior | Safety | Rating |
|---|---|---|---|
| Linked (default) | 70% menu | 20% | 10% |
| Linked + health focus | 75% menu | 15% | 10% |
| Unlinked (default) | 40% prior | 40% | 20% |
| Unlinked + health focus | 55% prior | 30% | 15% |

Health focus: BMI ≥ 25 or `weight-loss` goal.

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

| Check-in | Effect |
|---|---|
| Energy ≤ 2 | +5 light/healthy cuisines; −4 heavy/fast-food; MenuStat +3 if menu health ≥ 0.6, −3 if ≤ 0.35 |
| Energy ≥ 4 | +3 hearty cuisines (steakhouse, BBQ, Korean, …) |
| Mood ≤ 2 | +5 comfort cuisines (pizza, American, desserts, …) |
| Mood ≥ 4 | +3 light/healthy cuisines |
| Mood and energy = 3 | No change |

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

"Because you liked …" / "You liked this" goes before all of these.

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
    "Because you liked <name>" (shown first).
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
| `md_guides/ranking-v2-plan.md` | Design plan / remaining phases |
