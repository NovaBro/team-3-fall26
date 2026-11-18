# Ranking v2 plan: healthier restaurant ranking

Plan for replacing the current blended “healthiness” score with a
**menu-first nutrition estimate** that separates food *safety* from *nutrition*
and reports **confidence**. Current behavior is documented in
`md_guides/scoring-algorithm.md` (`search/recommend.py`, `search/menustat.py`).
Pipeline diagrams: `md_guides/scoring-pipeline.md`.

## Problem with v1

Today’s composite score mixes signals that mean different things:

| Signal | What it actually measures | Role in v1 |
|---|---|---|
| DOHMH grade | Food safety / cleanliness | 25% of score |
| Cuisine allow/deny lists | Weak stereotype | ±0.2 inside health component |
| Review keywords (`fresh` / `greasy`) | Noisy language, not nutrition | ±0.3 share of health |
| Fast-food name prefixes | Chain prior | −0.2 inside health |
| MenuStat median calories | Real nutrition (when linked) | Only 10%, sparse + often stale |
| Google / in-app rating | Taste & popularity | 15–25% of score |

Hard rules like “Japanese = healthy” / “Chicken = unhealthy” are often wrong.
Grade A is not “healthy food.” Keyword reviews are easy to game and miss context.
MenuStat covers mostly national chains and many rows are from **2017–2018**.

Users see one number labeled “Healthiness score” with no sense of how sure we are.

## Goals

1. Rank primarily on **nutrition evidence** when we have it.
2. Treat inspection grade as **safety** (filter / badge), not nutrition points.
3. Soften cuisine and reviews into **priors**, not dominant drivers.
4. Surface **confidence** (high / medium / low) next to any health estimate.
5. Keep Top Picks cheap: small candidate pool, limited Google calls, daily rotation.

Non-goals for this pass: full ML recommender, scraping every NYC menu, showing BMI.
Daily mood/energy check-ins (`md_guides/mood-energy-survey-plan.md`) apply as
**score adjustments / tags** in `score_restaurant()`, not as nutrition weights.

## Design principles

- **Don’t blend unlike quantities** into one opaque 0–100 without labels.
- **Prefer measured menu stats** over cuisine stereotypes.
- **Missing data → lower confidence**, not invented precision.
- **Safety can veto** “healthy picks” (e.g. hide or demote grade C / severe flags).
- Profile personalization (favorites, allergies, likes) stays as **adjustments / tags**,
  not part of the nutrition estimate itself.

## Proposed signal model

### A. Nutrition estimate (0–1) — primary “healthy vs unhealthy”

Compute when MenuStat (or a future menu source) links successfully:

- Qualifying meals: same category / protein / non-kids filters as today
  (`search/menustat.py`), require ≥3 items.
- Components (example weights, tune later):
  - **Calories:** `(800 − median_kcal) / 600` clipped to [0, 1] (reuse v1)
  - **Optional later:** sat-fat / sodium / sugar shares under thresholds;
    salad–veg / grilled share if categories allow
- Output: `menu_health ∈ [0, 1]`

When unlinked: **do not invent** a fake menu score. Fall back to a prior (below)
and mark confidence low.

### B. Safety (separate)

- Latest grade: A / B / C / pending
- Use as:
  - **Hard filter** for Top Picks: keep requiring latest grade A (or A/B with
    clear labeling)
  - **Badge / tag** on cards and detail (“Grade A”), not a large share of the
    nutrition number
- Optional later: demote places with recent critical violations

### C. Soft priors (only when menu is missing or as a small blend)

| Prior | Suggested strength | Notes |
|---|---|---|
| Cuisine | ±0.1 max | Shrink or retire hard `HEALTHY_CUISINES` / `UNHEALTHY_CUISINES` lists |
| Known fast-food / dessert chains | −0.15 to −0.2 | Keep name-prefix lists; omit places like Sweetgreen intentionally |
| Shop Healthy / farmers-market proximity | small + | Optional; use existing datasets |
| Reviews | capped ±0.1 | Prefer food-related reviews only; keyword or light classifier |

Reviews must not outweigh menu evidence when both exist.

### D. Popularity / quality (separate from health)

Google + in-app Bayesian rating stays useful for “is this place any good?” but
should be a **secondary sort or small weight**, not confused with healthiness.

### E. Confidence

| Level | When |
|---|---|
| **High** | Unambiguous MenuStat (or better) link + enough qualifying meals |
| **Medium** | Weak/ambiguous name match, or thin meal set, or menu year very old |
| **Low** | Cuisine/chain/review prior only |

UI: e.g. `Health estimate: 72 · medium confidence` plus the existing breakdown.

## Proposed ranking formulas

### Detail page / comparable “health estimate”

```text
if menu linked:
    health_estimate = 100 × menu_health
    confidence = high | medium  # from match quality + meal count + data age
else:
    health_estimate = 100 × clip(0.5 + cuisine_prior + chain_prior + review_prior)
    confidence = low
```

Profile deltas (favorite +10, dislike −15, nearby +5, feedback ±) stay as
**personalization adjustments** shown separately from the base estimate — same
idea as today’s breakdown, but not labeled as pure nutrition.

### Top Picks ordering score

Keep a single sort key for the pool, but make health dominate only when confident:

```text
if linked nutrition:
    sort_score = 100 × (
        0.70 * menu_health
      + 0.20 * safety_component   # mild; A already filtered
      + 0.10 * rating_component
    ) + profile_adjustments
else:
    sort_score = 100 × (
        0.40 * prior_health       # cuisine + chain + capped reviews
      + 0.40 * safety_component
      + 0.20 * rating_component
    ) + profile_adjustments
    # Prefer not to outrank high-confidence menu places solely on priors
```

Optional tie-break: among equals, prefer higher confidence, then rating, then
daily shuffle.

Candidate pool construction can keep today’s DB-only `explore_score` as a cheap
pre-filter, then re-rank the enriched pool with the formulas above.

## UI / product changes

1. Rename detail “Healthiness score” → **Health estimate** (or keep label but
   show confidence + parts).
2. Breakdown sections: **Nutrition** | **Safety** | **Rating** | **Your prefs**.
3. Reason tags: keep Grade A, Lower-calorie menu, Healthy reviews; add
   **Menu-based estimate** when linked; avoid implying cuisine alone means healthy.
4. Disclaimer when MenuStat year is old (already partly on detail/README).
5. Explore more: either show low-confidence prior ordering clearly, or sort by
   safety + weak prior without calling it “healthiest.”

## Migration plan

### Phase 0 — Document & measure (no behavior change)

- [ ] Log share of Top Picks / detail views with MenuStat link vs prior-only
- [ ] Spot-check misranked pairs (salad place vs fried-chicken “healthy cuisine”)

### Phase 1 — Confidence + split breakdown

- [x] Extend `score_restaurant` breakdown with `confidence` and labeled parts
- [x] Detail template: show confidence; clarify grade is safety
- [x] Tests in `search/test_recommend.py` for linked vs unlinked paths

### Phase 2 — Reweight formulas

- [x] Implement linked vs unlinked weight sets above
- [x] Shrink cuisine ±0.2 → ±0.1 (or config constants)
- [x] Cap review contribution
- [x] Raise MenuStat influence when linked (toward ~70% of base)
- [x] Update `md_guides/scoring-algorithm.md` to match shipped behavior

### Phase 3 — Better nutrition inputs

- [ ] Prefer durable CAMIS ↔ MenuStat map over fuzzy name match where possible
- [x] Flag / down-confidence menus older than a cutoff year
- [ ] Optional sat-fat / sodium if columns are reliable
- [ ] Optional Shop Healthy store boost for grocery-like places (if in scope)

### Phase 4 — Reviews (optional)

- [ ] Filter to food-related review text before keyword/classifier pass
- [ ] Light embedding or classifier for healthy-vs-unhealthy food mentions
- [x] Keep hard cap so reviews cannot dominate menu (review prior ±0.1)

## Code touchpoints

| Area | Files |
|---|---|
| Scoring API | `search/recommend.py` (`health_score`, `score_restaurant`, weights) |
| Menu / calories | `search/menustat.py` |
| Top Picks + detail | `search/views.py` (`_top_picks`, `restaurant_detail`, `_scored_restaurants`) |
| Templates | restaurant detail + Top Picks cards |
| Tests | `search/test_recommend.py`, `search/test_menustat.py`, `search/test_daily_feedback.py` |
| Current docs | `md_guides/scoring-algorithm.md` |

Keep `score_restaurant()` as the single pure function returning
`(score, tags, breakdown)`; extend `breakdown` rather than adding a parallel API
unless Claude picks need a different shape.

## Risks

- **Coverage bias:** MenuStat-heavy chains may dominate “high confidence” healthy
  ranks; local healthy spots stay low-confidence. Mitigate with clear UI and by
  not letting low-confidence priors beat strong menu scores unfairly.
- **Stale menus:** Old calories can mislead; confidence + disclaimer required.
- **Fuzzy match errors:** Ambiguous names should stay unlinked (already rejected).
- **Product confusion:** Users may still read any number as “official healthiness”;
  labeling and breakdown matter as much as the formula.

## Success criteria

- Linked places: ordering agrees more often with lower median qualifying calories
  / saner meal mix than with cuisine stereotypes.
- Unlinked places: never look “precisely scored”; confidence is low and UI says so.
- Grade remains visible but is not the main story of “healthy food.”
- Top Picks Google call budget stays on the order of today’s ~9–15 candidates.
- Existing feedback / diversity / daily rotation behavior still works.

## Open questions

1. Should Top Picks **exclude** low-confidence places when enough high-confidence
   candidates exist in the borough that day?
2. Exact thresholds for medium vs high confidence (meal count, match type, year).
3. Whether Explore more should use the new estimate or stay on cheap `explore_score`.
4. How much profile BMI / weight-loss “health focus” should still shift weights once
   nutrition is primary (maybe only affect calorie thresholds, not grade share).

## References

- Current algorithm: `md_guides/scoring-algorithm.md`
- Datasets: `AGENTS.md`, `md_guides/dataset_setup.md`
- MenuStat limits and fuzzy match: `search/menustat.py`
