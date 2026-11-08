# Top Picks scoring algorithm

HealthyFoodsNYC ranks a small pool of recent grade-A restaurants and shows the
top three on `/home/` (first page, no borough filter). Scoring is rule-based in
`search/recommend.py` (`score_restaurant`). MenuStat linking and meal filters
live in `search/menustat.py`.

## Setup (candidate flow)

1. Start from distinct grade-A inspection rows (up to 9 by latest inspection date).
2. Exclude cuisines that are risky for the user’s free-text allergies (via
   `diet_filters.risky_cuisines` after keyword → `nuts` / `shellfish` mapping).
3. For logged-in users with a profile, add up to 3 favorite-food matches and up
   to 3 same-borough-as-home places (15 candidates max).
4. Enrich with Google Places (rating, price, up to 5 reviews), DOHMH grade, and
   in-app ratings; optionally resolve MenuStat calories by **fuzzy name match**.
5. Score each candidate; show the top 3 with up to three reason tags.

Price is **not** part of the numeric score (Budget-friendly is a tag only).
BMI is never shown on the page; it only shifts weights.

## Components (0–1)

| Part | How it is computed |
|---|---|
| **Health** | Base 0.5 ± 0.2 cuisine ± 0.3 × (healthy − unhealthy review share) − 0.2 if fast-food chain; clipped to [0, 1]. |
| **Inspection grade** | A = 1.0, B = 0.5, C = 0, pending/missing = 0.3. |
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

## Reason tags (max 3, fixed order)

1. Your favorite  
2. Nearby  
3. Healthy reviews (≥2 healthy reviews and ≥40% of reviews)  
4. **Lower-calorie menu** (MenuStat linked and calorie component ≥ 0.6, i.e. median ≤ 440 kcal)  
5. Budget-friendly (Google price `$`)  
6. Top rated (50+ votes, blended ≥ 4.5)  
7. Grade A  

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
