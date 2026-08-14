# nineproj — 2026-27 9-Cat Fantasy Projections

Research-driven player projections and rankings for 2026-27 NBA head-to-head
9-category fantasy basketball. A Python pipeline (`nineproj`) blends three
prior seasons of NBA Stats data with a hand-curated research evidence store
(consensus rankings, transactions, injuries, role notes, rookie comps) into a
validated Top-200 dataset, and a standalone React dashboard renders it for
browsing, mover analysis, and live weight tuning. Every number in the output
traces back to either box-score history or a cited source in the evidence
store — nothing is invented.

## Quickstart

### Install

```
cd projections && uv sync
cd projections/dashboard && npm install
```

### Run the pipeline

```
cd projections
uv run python run_projection.py
```

This fetches three prior seasons of NBA Stats data (or reads the on-disk
cache if warm), loads the research evidence store, runs every projection
stage, and writes `data/players_2026_27.json` (+ CSV + `data/sources.json`
provenance) plus a `validation/report.json`.

Useful flags (see `run_projection.py`):

- `--offline` — cache/fixtures only, never calls `nba_api` live; fails loudly
  (exit 3) on a cold cache instead of running over partial data. Used by CI
  and the end-to-end test.
- `--validate-store` — only loads and schema-validates the research evidence
  store (`nineproj.research.store.load_store`), then exits; does not run the
  pipeline. Use this after editing evidence JSON.
- `--cache-dir PATH` — override where the on-disk NBA Stats cache lives.
- `--research-dir PATH` — override the evidence store directory (default
  `data/research`).
- `--output PATH` / `--csv PATH` / `--sources PATH` — override the dataset
  JSON / CSV / provenance output paths.
- `--report PATH` — override the validation report path.
- `--projection-date YYYY-MM-DD` — override "today" for age/injury-timeline
  math (default: actual today).

Exit codes:

- `0` — success, dataset validated.
- `1` — `--validate-store` only: the evidence store failed schema validation.
- `2` — dataset built but failed validation (`validation/report.json` has a
  `fail`).
- `3` — season or evidence data acquisition failed (e.g. `--offline` with a
  cold cache, or a live fetch that exhausted retries with no cached
  fallback).

### Run the dashboard

```
cd projections/dashboard
npm run dev
```

`npm run dev` runs a `predev` hook (`scripts/sync-data.mjs`) that copies
`data/players_2026_27.json` into `dashboard/public/data/` automatically, so
the dashboard always reflects the latest pipeline output without a manual
copy step. If the pipeline hasn't been run yet, the sync script warns and
skips rather than failing the dev server.

### Run tests

```
cd projections && uv run pytest
cd projections/dashboard && npx vitest run
```

## Data sources

**NBA Stats (`nba_api`)** — per-game stat lines for the three prior seasons
(`2025-26`, `2024-25`, `2023-24`), team rosters (for position enrichment),
and the 2026-27 schedule (for fantasy-week/playoff-window math). Every live
fetch goes through an on-disk JSON cache under `data/raw/` with a
configurable TTL (`cache.ttl_hours` in `config/settings.json`, currently 24h),
retries, a minimum gap between live calls to avoid hammering `stats.nba.com`,
and a stale-cache fallback so a live failure doesn't take down the run.

**Research evidence store (`data/research/`)** — schema-validated JSON files,
each entry carrying a cited source (name, URL, retrieval date, quality tier,
source type). As of the current run:

- 4 consensus lists: RotoWire (top-150, Roto/Points), ESPN Way-Too-Early
  (top-150), Sports Illustrated/OnSI (top-50), Slamdex ADP (150, aggregated
  from Yahoo/ESPN/Fantrax).
- 75 transactions (trades, signings, retirements, coaching changes).
- 28 injury notes.
- 30 role notes (usage/minutes changes tied to a specific piece of evidence).
- 14 rookie notes.
- 0 sentiment notes (see Limitations).

Full provenance — including sources that were *attempted but inaccessible* —
is recorded in `data/sources.json`. Documented access failures: Hashtag
Basketball fantasy rankings (HTTP 403), Basketball Monster projections
(paywalled — no `statistical_model`-type source exists anywhere in the store
as a result), FantasyPros overall rankings (client-side rendered, no rows
capturable), and r/fantasybball community threads (platform-level crawler
block). Because Reddit is inaccessible, community sentiment is absent from
the store, and the consensus component's weighting for a missing source type
is simply not applied for that player rather than substituted with a guess.

## Methodology

Every stage below is settings-driven (`config/settings.json`) and pure
(no I/O beyond the stats/research fetchers at the top of the pipeline).

### Baseline

Marcel-style projection: per-game rates from the three prior seasons are
blended with a recency-weighted 5/3/1 scheme (most recent season weighted
5x), minutes-weighted so seasons with more playing time count for more,
then regressed toward the player's position-group mean (guard/forward/center)
in proportion to how far their career minutes are from a "full sample"
threshold (`baseline.full_sample_minutes`, 4500 minutes). An age curve then
scales the regressed rate up for players still improving (under
`age_curve.improve_until`), down after `decline_after`, and more steeply
after `steep_decline_after`, clamped to a floor/ceiling multiplier so no age
effect distorts the rate too far. Makes (FGM/FTM) are rebuilt from the aged
percentage times the aged attempts, rather than aged directly, so a make
total can never exceed its attempt total.

### Role/team-change adjustment

Every `RoleNote` for a player (usage/minutes deltas backed by a specific
transaction or beat report) is combined into one bounded delta: minutes
capped at ±8 min (`adjustment_caps.minutes_delta`), usage capped at ±5
percentage points of a 25%-usage league-average workload
(`adjustment_caps.usage_delta`). Each note is weighted by its source's
quality tier, and conflicting notes about the same player apply a penalty
rather than simply averaging out. A separate team-pace adjustment (per-team
possession proxy derived from the prior season's stat lines) rescales
counting stats when a player changes teams or league pace shifts, capped at
±5% (`adjustment_caps.pace_multiplier`). A player with no role evidence keeps
a stable-role assumption at reduced (0.7) confidence rather than full (1.0)
certainty.

### Games-played / injury

`raw_projected_games` blends the last three seasons' games-played
(recency-weighted, lightly regressed toward the league median). A separate
injury risk score folds in age (higher penalty bands over 28/32/34), a
chronic-condition flag, and any currently reported injury timeline from the
evidence store, capped so a single reported absence can't dominate the
score. Where an evidence source gives a concrete return-timeline estimate,
that acts as a ceiling on projected games rather than a floor. Raw and
risk-adjusted games are both kept in the output (not just the adjusted
figure) so the composite/dashboard layers can see the pre- and post-shrink
numbers separately.

### Rookies

Rookies have no NBA Stats history to project from, so a rookie is only
included if its evidence note carries *both* a minutes range and a
comp-derived per-minute rate band (i.e. an analyst-cited statistical
comparison, not a vibes-based projection). A note missing either is excluded
from the pool entirely rather than projected with invented numbers — this is
why most of the 2026 rookie class does not appear in the Top 200.

### 9-cat valuation

Reuses the app's existing, tested `ninecat.engine.zscores` engine rather than
recomputing fantasy category math: volume-weighted z-scores for FG%/FT%
(impact-weighted by attempt volume, not raw percentage), turnovers inverted
(fewer is better), and z-scores for the other counting categories. Two value
figures are computed per player: per-game value (rate-only) and
availability-adjusted value (rate x projected games, so a talented but
injury-prone player is discounted relative to a healthy one at the same
per-game level). A scarcity score credits players whose z-score clears a
fixed threshold (1.0) in categories where few players do, and single-category
punt values are computed for each of the 9 categories.

### Playoffs

Fantasy playoff weeks (`playoff_window.start_week`/`end_week`, currently
weeks 19–21) get their own schedule-weighted value, blended with the
regular-season value at a 75/25 split (`value_split`). The full 2026-27
schedule is published and ingested, so this component is live in the
current run. Safety net for future seasons: if the fetched schedule has
zero games league-wide inside the playoff window (a partial early-summer
release), the pipeline treats every player's playoff contribution as
unavailable rather than computing it from an incomplete schedule —
`validation/report.json` reports a `warn` (`playoff_window_coverage`) and
the composite weight normally allocated to `playoff_schedule` (5%)
redistributes across the player's other available components until a
re-run picks up the full schedule.

The pipeline also precomputes the same per-player schedule/value fields for
every option in `candidate_playoff_windows` (17–19 through 22–24, settings.json),
not just the primary `playoff_window` — each player's exported
`schedule.windows` map holds one entry per option (`week_games`,
`playoff_games`, `playoff_b2bs`, `playoff_schedule_score`,
`expected_playoff_games`, `playoff_value_z`), so the dashboard can swap
playoff weeks client-side without a pipeline re-run. The shipped default
fields are always identical to `schedule.windows["19-21"]` (same underlying
computation, not a second copy).

### Consensus

Each of the 4 consensus lists is weighted by its source type (e.g.
`expert_rank` at 0.30, `adp` at 0.10 — see `consensus.source_type_weights`
in settings) times its quality tier (`very_high` 1.0 down to `low` 0.15).
Player-level ranks across the weighted lists are averaged into one
consensus rank; a player missing from a given list is imputed with a rank
penalty past that list's length (`consensus.imputation_penalty`) rather than
excluded. Rank variance across sources is tracked, and two flags are
produced: `model_loves`/`model_fades` when the model's rank differs from
consensus by more than `disagreement_rank_threshold` (15 spots), and
`high_uncertainty` when rank variance across sources exceeds
`high_variance_threshold`.

### Composite

Eight configurable weights (`composite_weights` in settings: per-game 40%,
availability-adjusted 20%, expected games 10%, role/usage 10%, playoff
schedule 5%, consensus 5%, team environment 5%, category scarcity 5%,
summing to 1.0) combine into one final score per player. Weights are
renormalized per-player over whichever components that player actually has
available (e.g. a player with a force-unavailable playoff component gets
their remaining weights rescaled to still sum to 1.0). `model_rank` is
computed excluding the consensus component, so the dataset can show how much
of the final rank consensus alone moved a player.

Component scales differ by design, and a weight is each component's
influence *within its own scale*, not an absolute cap on its pull: `per_game`,
`availability_adjusted`, `expected_games`, `playoff_schedule`,
`category_scarcity`, and `consensus` are population z-scores over the current
pool (unbounded — how much a z component actually moves the score still
depends on how spread out the pool is on that quantity), while `role_usage`
and `team_environment` are bounded `[-1, 1]` capped nudges (deliberately
small, fixed-scale signals derived from settings-capped deltas, e.g. pace
change relative to `adjustment_caps.pace_multiplier`) — a bounded component's
weight *is* its maximum possible pull, except when the per-player
renormalization above is actively redistributing another component's weight
away (e.g. `playoff_schedule` while the season's schedule is unpublished): a
bounded nudge's *effective* weight then inflates slightly above its
configured value (0.05 → ~0.0526 at today's redistribution) for as long as
that other component stays pool-wide unavailable, and reverts once it
publishes. A 0–100 confidence score
(sample size, injury uncertainty, role uncertainty, source agreement) is
banded into high/medium/low (`confidence_bands`: 75/55). Every
strengths/risks/summary explanation is assembled from a deterministic
template over the player's own stored numbers — no free-form narrative
claim is made without a number backing it.

## Configuration

`config/settings.json` is the single source of truth for every weight,
window, and cap in the pipeline — composite weights, playoff window, value
split, consensus source/tier weights, baseline blend/regression/age-curve
constants, adjustment caps, availability thresholds, confidence bands, cache
TTL, and games bounds. `Settings` is loaded once via
`nineproj.config.load_settings` and validated (composite weights and value
split must each sum to 1.0, playoff window ordering, no negative weights) —
a malformed settings file fails loudly at startup rather than silently
degrading.

Changing composite weights **client-side**, in the dashboard's Settings tab,
re-ranks the Top 200 live using the component scores already shipped in
`players_2026_27.json` — no pipeline re-run needed for weight experimentation.
Anything deeper than the 8 composite weights (baseline math, role/usage caps,
availability model, consensus source weighting, etc.) requires editing
`config/settings.json` and re-running the pipeline.

## Dashboard usage

- **Rankings** — sortable table over the Top 200 with search, filters, and an
  optional-column picker (z-scores, age, value figures) layered on top of a
  default column set. Selecting a row opens a detail panel with the
  player's per-category z-score profile and availability chart.
- **Playoff weeks dropdown** — a labeled selector in the header (17–19
  through 22–24, default 19–21) lets a league pick its own playoff schedule;
  changing it swaps every player's playoff component to that window's
  precomputed value and re-ranks the Rankings table, Movers' Playoff Boosts,
  and the detail panel's schedule section client-side, composing with any
  Settings weight changes. A muted note appears whenever a non-default window
  is selected. This dropdown replaces the old numeric "min playoff schedule
  score" filter, which is removed.
- **Movers** — model risers/fallers (vs. consensus rank), injury-discounted
  players, playoff-schedule boosts, and rookie/breakout candidates, plus a
  disagreement chart visualizing model rank vs. consensus rank across the
  pool.
- **Settings** — weight sliders for the 8 composite components; dragging a
  slider recomputes and re-sorts the Top 200 live from the shipped component
  scores (debounced to avoid jank on drag).

## Limitations

Be aware of these before trusting a specific rank:

- **The research evidence store is refreshed manually/by an agent**, not by
  an automated scraper. There is no scheduled job keeping consensus lists,
  injuries, or role notes current — refreshing it is a deliberate,
  human/agent-driven step (see "How to update" below).
- **No `statistical_model`-type source is captured.** Basketball Monster is
  paywalled and Hashtag Basketball returns HTTP 403; every consensus list in
  the store is `expert_rank` or `adp`, so the `statistical_model` slice of
  `consensus.source_type_weights` currently has nothing to weight.
- **Consensus is 4 lists with uneven depth** — RotoWire and ESPN each carry
  ~150 players, SI only 50, and ADP 150 — so consensus coverage thins out
  fast past roughly rank 150.
- **Community/Reddit sentiment is absent.** `data/research/sentiment.json`
  has 0 entries because r/fantasybball is crawler-blocked; resolving this
  needs an authenticated Reddit path (API credentials or an MCP tool), not
  another fetch attempt.
- **Playoff-schedule data depends on the NBA's release cadence.** The full
  2026-27 schedule is now ingested and the playoff component is live; if a
  future season's run happens before the full schedule drops, the component
  goes force-unavailable (weight redistributed) until a re-run after release.
- **Long-tail players (below roughly the top 150) are stats-only** — no
  research evidence backs them individually, so their confidence score is
  lower and their projection leans entirely on the baseline/availability
  models.
- **Rookies without a comp-derived per-minute band are excluded from the Top
  200**, including most of the 2026 draft class. This is deliberate
  conservatism (see Methodology → Rookies), not an oversight.
- **This is not betting or medical advice.** Projections are a fantasy
  draft/roster tool built from public stats and cited news reporting; injury
  timelines in particular reflect reported (sometimes disputed) estimates,
  not clinical judgment.

## How to update

1. **Refresh evidence JSON** under `data/research/` (consensus lists,
   transactions, injuries, roles, rookies, sentiment) — respect the existing
   schema (`nineproj/research/schema.py`) and always cite a source.
2. **Validate the store** before running the full pipeline:
   `uv run python run_projection.py --validate-store` (exits 1 on a schema
   failure).
3. **Clear or let expire the NBA Stats cache** under `data/raw/` if the
   underlying season data itself needs to be re-fetched (the TTL is 24h by
   default; delete the relevant cache file(s) to force an earlier refresh).
4. **Re-run the pipeline**: `uv run python run_projection.py`. Confirm
   `validation/report.json` status is `pass` (a `playoff_window_coverage`
   `warn` is expected until the full schedule is published).
5. **Sync the dashboard's data**: `npm run sync-data` (or just `npm run dev`,
   which runs it automatically via `predev`).

A **season rollover** (e.g. moving from 2026-27 to 2027-28) is a
`config/settings.json` change: update `season`, `prior_seasons`, and
`fantasy_week1_start`, then follow the same refresh-evidence → validate →
re-run → sync sequence above.
