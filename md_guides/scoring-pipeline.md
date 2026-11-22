# Restaurant scoring pipeline

End-to-end view of how Today's Top Picks and restaurant detail pages get a
score. **Shipped math and tables:** [`scoring-algorithm.md`](scoring-algorithm.md).
**Design history:** [`ranking-v2-plan.md`](ranking-v2-plan.md).

Core API: pure `score_restaurant()` in `search/recommend.py` (no I/O). Wiring
and enrichment live in `search/views.py`.

---

## 1. End-to-end Top Picks pipeline

```mermaid
flowchart TD
  subgraph candidates [1. Candidate pool - DB only]
    A["Explore ranking<br/>grade / cuisine / fast-food / staleness"] --> B["Daily shuffle<br/>seed = date + user + borough"]
    B --> C["First 25 meal places<br/>grade A, max 5 per cuisine"]
    C --> D{Logged-in profile?}
    D -->|yes| E["+ up to 3 favorite matches<br/>+ up to 3 near-home"]
    D -->|no| F["Pool max 25"]
    E --> F2["Pool max 31"]
    F --> MX{Mood check-in today?}
    F2 --> MX
    MX -->|yes| MY["+ up to 8 mood-matched cuisines<br/>pool max 39"]
    MX -->|no| G
    MY --> G["Drop Not interested<br/>Drop strong allergy cuisines"]
  end

  subgraph enrich [2. Enrich each candidate]
    G --> H["Google Places<br/>rating, price, up to 5 reviews, photo"]
    H --> I[DOHMH latest grade]
    I --> J["MenuStat fuzzy name match<br/>median qualifying-meal calories"]
    J --> J2["No MenuStat: Gemini-estimated menu<br/>stored MenuEstimate median kcal"]
    J2 --> K["AI health score<br/>HealthScore or MiniLM live"]
    K --> L[In-app ratings]
  end

  subgraph score [3. Score]
    L --> M["score_restaurant(...)<br/>sort_score, tags, breakdown"]
  end

  subgraph select [4. Select top 3]
    M --> N{"Claude personalized picks?<br/>logged-in, no borough, key set"}
    N -->|yes| O["Keep Claude order<br/>still attach scores/tags"]
    N -->|no| P["pick_top<br/>one cuisine each<br/>at most 1 like-bonus winner"]
    O --> Q[Today's Top Picks cards]
    P --> Q
  end
```

**Explore more** uses only step 1's cheap `explore_score` (no Google / MenuStat /
AI). Top Picks re-scores the enriched pool with the full formula.

**Detail page** (`/restaurant/<camis>/`) skips the pool: `score_for_camis` loads
Google / MenuStat / AI / ratings for one place, then calls the same
`score_restaurant`.

---

## 2. Score calculation

```mermaid
flowchart TD
  IN["Inputs: name, cuisine, grade, ratings, reviews<br/>profile, feedback, mood, MenuStat, AI scores"] --> NUT

  subgraph nutrition [Nutrition 0-1]
    NUT{"MenuStat linked<br/>calorie_score set?"}
    NUT -->|yes| MENU["menu_health =<br/>(800 - median_kcal) / 600 clipped"]
    NUT -->|no| PRIOR["prior_health =<br/>0.5 +/- cuisine +/- reviews - fast-food"]
    PRIOR --> REV{ai_health present?}
    REV -->|yes| AI["reviews = 1.0 x (ai - 0.5)"]
    REV -->|no| KW["reviews = 0.3 x keyword share"]
  end

  AI --> EST{Estimated menu stored?}
  KW --> EST
  EST -->|yes| MIX["nutrition = 0.5 x estimated menu_health<br/>+ 0.5 x prior_health (low confidence)"]
  EST -->|no| BLEND
  MIX --> BLEND
  MENU --> BLEND

  subgraph other [Other components 0-1]
    SAFE["Safety: grade A=1, B=0.5, C=0, missing=0.3"]
    RATE["Rating: Bayesian Google+app, map 3 stars to 0 ... 5 stars to 1"]
    FIT{Personal inputs?}
    FIT -->|yes| PF["Personal fit 0-1<br/>favorites, goals, likes, home, allergies"]
    FIT -->|no| NOP[Skip personal term]
  end

  SAFE --> BLEND
  RATE --> BLEND
  PF --> BLEND
  NOP --> BLEND

  BLEND["sort_score =<br/>100 x sum(component x weight)<br/>+ mood/energy point deltas"]
  BLEND --> OUT["Return: sort_score, tags max 5, breakdown"]
```

### Formula

```text
sort_score =
  100 × (nutrition × w_n + safety × w_s + rating × w_r [+ personal × w_p])
  + mood_overlay (2H: high→healthier, low→laxer)
```

| Mode | Nutrition / prior | Safety | Rating | Personal |
|---|---|---|---|---|
| Linked (MenuStat) | 70% | 20% | 10% | — |
| Linked + health focus | 75% | 15% | 10% | — |
| Unlinked | 40% | 40% | 20% | — |
| Unlinked + health focus | 55% | 30% | 15% | — |
| Any + personal inputs | base × 0.80 | | | 20% |

**Health focus:** BMI ≥ 25 or `weight-loss` goal (BMI is never shown; it only
shifts weights).

**Health estimate** (detail headline, not the sort total):

```text
if MenuStat linked:  100 × menu_health
else:                100 × prior_health
```

Shown with confidence: **high** (exact match, ≥5 meals, year ≥ 2019) /
**medium** (fuzzy/stale/thin menu) / **low** (prior only).

---

## 3. Nutrition path in detail

```mermaid
flowchart LR
  NAME[Restaurant DBA] --> MATCH{"Fuzzy MenuStat match<br/>exact then prefix then contains"}

  MATCH -->|at least 3 qualifying meals| MED["Median kcal of meals<br/>Entrees/Sandwiches/Salads/...<br/>protein >= 15g, not kids"]
  MED --> MH["menu_health 0-1"]

  MATCH -->|no / thin| BASE[prior base 0.5]
  BASE --> CUI["Cuisine +/- 0.2"]
  CUI --> REV2["AI reviews +/- 0.5<br/>or keywords +/- 0.3"]
  REV2 --> FF["Fast-food name -0.2"]
  FF --> PH["prior_health clipped 0-1"]
```

Qualifying meal filters and match rules: `search/menustat.py`.

---

## 4. AI health score path (not an LLM API)

Numeric store health scores use **MiniLM sentence embeddings**, not Gemini or
Claude. Gemini's only effect on scores is the offline estimated-menu calories
(blended into nutrition when there is no MenuStat menu); otherwise the LLM
APIs write reason prose / read menus / chat / optional re-order.

```mermaid
flowchart TD
  subgraph inputs [Text inputs]
    R["Google review texts up to 5"]
    M["MenuStat meal name + description<br/>if chain matched"]
  end

  R --> LIVE
  M --> LIVE

  subgraph store [Cache]
    DB[("community.HealthScore<br/>camis, score, goal_scores")]
  end

  LIVE{Row with goal_scores?}
  LIVE -->|yes| REUSE[Reuse stored score]
  LIVE -->|no + AI_LIVE_SCORING| ENC["all-MiniLM-L6-v2<br/>fastembed or sentence-transformers"]
  ENC --> CMP["Cosine vs healthy/unhealthy<br/>and per-goal anchors"]
  CMP --> SHRINK["Average, shrink toward 0.5"]
  SHRINK --> SAVE[update_or_create HealthScore]
  SAVE --> USE
  REUSE --> USE["ai_health, ai_goals"]

  USE --> RANK["recommend.health_parts / personal_fit"]

  BATCH[manage.py score_health] -.->|offline fill| DB
  DB -.-> LIVE
```

| Related LLM | Role | Changes score? |
|---|---|---|
| MiniLM (`search/health_ai.py`) | Health + goal floats 0–1 | Yes — feeds prior / personal fit |
| Gemini (`search/reason_writer.py`) | Detail “why” paragraph | No |
| Gemini (`search/what_to_order.py`) | Reads menu photos for the Menu box (live, not stored) | No |
| Gemini (`search/menu_estimate.py`) | Estimated menu + kcal per dish (offline, stored) | Yes — 50% of nutrition when no MenuStat |
| Anthropic (`assistant/llm.py`) | Chat; optional Claude Top Picks order | Order only when used; still runs `score_restaurant` for tags |

Fallback when AI missing: review **keyword** counts in `health_parts`.

---

## 5. Personal fit and mood (after / beside the blend)

```mermaid
flowchart TD
  subgraph personal [Personal fit - 20 percent weight when active]
    S["Start 0.5"] --> F["+0.3 favorite / -0.4 disliked"]
    F --> G["Goals: 1.2 x (avg_fit - 0.5)<br/>AI goals + MenuStat nutrients"]
    G --> BMI["BMI 25+: half-strength weight-loss fit"]
    BMI --> A["-0.2 per mild allergy cuisine hit"]
    A --> H["+0.1 near home ZIP or borough"]
    H --> L["+0.1 per liked same-cuisine place<br/>cap 0.3"]
    L --> N["-0.2 if 2+ Not interested in cuisine"]
    N --> PF["Personal fit clipped to 0-1<br/>enters blend at weight w_p"]
  end

  subgraph mood [mood_overlay - absolute points after the blend]
    CHECK["Today MoodLog check-in"] --> STR["Strictness = avg(mood, energy)<br/>missing side counts as 3"]
    STR --> HI["High, avg >= 4:<br/>12 x (nutrition - 0.5)<br/>+8 light / -6 heavy or fast food"]
    STR --> MID["Mid: no cuisine/nutrition overlay"]
    STR --> LO["Low, avg <= 2:<br/>-6 x (nutrition - 0.5)<br/>+12 comfort / +8 hearty"]
    CHECK --> DIST["With user pin + place coords:<br/>distance x energy curve"]
    HI --> MD["mood_delta added to sort_score"]
    MID --> MD
    LO --> MD
    DIST --> MD
  end

  PF --> SORT["sort_score"]
  MD --> SORT
```

Strong allergy cuisines are **excluded from the candidate pool**, not scored as
a soft penalty. Mood/energy rows appear under `breakdown["adjustments"]`; they
do not change `health_estimate`.

After a check-in, the home page calls `rerank/`, which reapplies
`mood_overlay` to the cached scored pool (no Google / MenuStat / AI calls) and
swaps in new Top Picks cards.

When mood and energy are both ≥ 4, home also shows a separate **Cook at home
today** strip (`search/cook_at_home.py`) with farmers markets and Shop Healthy
stores (Google enrichment must be ≥4★ and ≥100 reviews) — not part of the
restaurant sort score.

With a saved location pin and a mood check-in, restaurant sort scores also get
a **distance × energy** adjustment (low energy favors closer places). See
[`ranking-location-mood-plan.md`](ranking-location-mood-plan.md).

---

## 6. Outputs

```python
score, tags, breakdown = score_restaurant(...)
```

| Field | Use |
|---|---|
| `score` | Top Picks sort key (~0–100+, mood can push above 100) |
| `tags` | Card chips (≤5), fixed `TAG_ORDER` |
| `breakdown["health_estimate"]` | Detail nutrition headline |
| `breakdown["confidence"]` | high / medium / low |
| `breakdown["parts"]` | Weighted lines for the detail ranking UI |
| `breakdown["adjustments"]` | Mood/energy rows |
| `breakdown["reasons"]` | Up to 3 “why this pick” sentences |
| `breakdown["like_bonus"]` / `similar_to` | Diversity + tooltip |

Optional Gemini paragraph (`ReasonBlurb`) is layered on the detail page from
general reasons only — never personal facts, never review text.

---

## 7. Code map

| Step | Module |
|---|---|
| Candidate pool / Explore score | `search/views.py` (`_build_candidate_pool`, `_scored_restaurants`) |
| Google enrichment | `search/services/places.py`, `restaurants/places.py` |
| MenuStat link + calories | `search/menustat.py` |
| Gemini-estimated menus | `search/menu_estimate.py`, `manage.py estimate_menus` |
| MiniLM health / goals | `search/health_ai.py`, `search/ai_scores.py` |
| Pure score | `search/recommend.py` (`score_restaurant`, `health_parts`, `personal_fit`, `pick_top`) |
| Goal nutrient fit | `search/goal_fit.py` |
| Top Picks / detail wiring | `search/views.py` (`_top_picks`, `score_for_camis`) |
| Claude optional order | `assistant/recommend.py` (`personalized_picks`) |
| Gemini reason prose | `search/reason_writer.py` |
| Batch AI scores | `manage.py score_health` |
| Batch Gemini blurbs | `manage.py write_reasons` |

---

## 8. Related docs

| Doc | Contents |
|---|---|
| [`scoring-algorithm.md`](scoring-algorithm.md) | Full tables, tags, MenuStat filters, daily rotation, limits |
| [`ranking-v2-plan.md`](ranking-v2-plan.md) | Why nutrition/safety split and linked vs unlinked weights |
| [`mood-energy-survey-plan.md`](mood-energy-survey-plan.md) | MoodLog check-in UX and storage |
