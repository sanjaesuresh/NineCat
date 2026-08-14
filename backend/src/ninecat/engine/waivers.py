"""Pure waiver-candidate scoring: rank available free agents by how much they
would help THIS roster THIS week, weighted by which categories the current
matchup is close in and which categories the roster's build actually needs.

No DB access and no dependency on ninecat.models, exactly like zscores.py and
streaming.py -- callers (the Task 3 adds endpoint) adapt their own free-agent
rows into WaiverCandidate before calling in. No clock, no randomness: games
remaining in the scoring period is the caller's responsibility, passed in as
WaiverCandidate.games_remaining.

Category weight reuses engine.needs.need_weights (see docs/waiver-valuation-
plan.md W5 -- extracted specifically so the draft recommender and this module
can never drift on what counts as a "need") plus a flat bonus for categories
the matchup says are close, then forces punted categories to zero -- see
score_waiver_candidates's docstring for the exact punt-vs-close ordering.

This module owns only HOW to present the ranked list. The sign rule,
per-category scaling, worth-it gate, and "helps X" rule (tov included) all
live in engine.contribution and are shared verbatim with engine.streaming
(which owns WHEN to add someone) -- see that module's docstring for the
reasoning behind each. Two modules answering "which free agent helps me this
week" must never independently reinvent, and disagree on, the same rules;
this module used to have its own private, correct-but-duplicated
_signed_contribution, which is why the extraction happened.

Reason token vocabulary (WaiverScore.reasons), structured contract-key
tokens only -- the frontend composes the sentence (see
components/dashboard/categoryKeys.ts). Emitting English prose here was a
review finding on two earlier tasks; do not repeat it:
  "category:<key>"          -- one per entry in categories_helped, contract
                                key from engine.zscores.CATEGORIES (e.g.
                                "category:pts"), canonical order. For
                                "category:tov" specifically: this only
                                appears when the candidate's raw tov rate is
                                LOW (< engine.contribution.LOW_TOV_RATE) AND
                                games_remaining > 0 -- a candidate who adds
                                turnovers at or above LOW_TOV_RATE, or who
                                does not play at all, is never tagged as
                                helping tov, by construction (see
                                engine.contribution.helps_category).
  "schedule_driven"          -- this candidate's games_remaining is at least
                                SCHEDULE_EDGE_GAMES (a full game) above the
                                mean games_remaining across every candidate
                                passed into this call, i.e. their schedule
                                (not their per-game rates alone) is doing
                                real work in their score. A full-game margin,
                                not merely "above average", keeps the token
                                rare and legible against a large free-agent
                                pool (~69 seeded candidates) where "above the
                                mean" alone would fire on roughly half of
                                them and become noise.
  "season_average_fallback"  -- stat_basis == "season_average": the rates
                                behind this score are last season's averages,
                                not a live projection, surfaced so the UI can
                                be honest about the basis (W4/W1).

A candidate whose total score is at or below zero is dropped from the
result entirely -- see engine.contribution.is_worth_it and
score_waiver_candidates's docstring. Scoring a net-zero or net-negative add
as a "top recommendation" (a real bug this module shipped with: a
zero-games candidate scored exactly 0.00 and ranked #1, tagged as helping
turnovers, above real contributors sitting at negative scores) is worse
than showing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from ninecat.engine.contribution import (
    LOW_TOV_RATE,
    category_reason_token,
    helps_category,
    is_worth_it,
    scaled_contribution,
)
from ninecat.engine.needs import need_weights
from ninecat.engine.zscores import CATEGORIES

# flat weight bump for a category the matchup comparison classifies as close
# (see engine.matchup.MatchupComparison.close_categories) -- on top of, not
# instead of, the roster's own need weight, so a category can be both a need
# AND close and get credit for both.
CLOSE_CATEGORY_WEIGHT = 1.0

# how far above the batch's mean games_remaining a candidate must sit to earn
# the "schedule_driven" reason token -- a full game, the unit a fantasy
# manager actually thinks in, not just "any amount above average" (see
# module docstring for why "above average" alone is too noisy at pool scale).
SCHEDULE_EDGE_GAMES = 1.0

REASON_SCHEDULE_DRIVEN = "schedule_driven"
REASON_SEASON_AVERAGE_FALLBACK = "season_average_fallback"

_SEASON_AVERAGE_BASIS = "season_average"


@dataclass(frozen=True)
class WaiverCandidate:
    """One available free agent: their per-game category rates over the
    remaining days of the scoring period, and how many games they play in
    that window. rates is RAW -- rates["tov"] is a positive turnovers/game
    count, NOT pre-inverted like engine.zscores output (see module
    docstring). stat_basis carries through to WaiverScore for UI honesty
    about whether rates are a live projection or a season-average fallback.
    """

    player_key: str
    games_remaining: float
    rates: dict[str, float]
    stat_basis: str


@dataclass(frozen=True)
class WaiverScore:
    """One candidate's ranked result: their score, the categories they
    actually help (weight > 0 AND a genuine help per
    engine.contribution.helps_category -- see _helps_category), and
    structured reason tokens (see module docstring)."""

    player_key: str
    score: float
    games_remaining: float
    categories_helped: tuple[str, ...]
    stat_basis: str
    reasons: tuple[str, ...]


def _helps_category(cat: str, weight: float, rate: float, games_remaining: float) -> bool:
    """A category only counts as "helped" if it has any weight at all (a
    category with zero weight -- e.g. punted, or not a need and not close --
    is never a reason to add anyone) on top of the shared rate/games rule
    (see engine.contribution.helps_category, and module docstring for the
    tov specifics)."""
    if weight <= 0.0:
        return False
    return helps_category(cat, rate, games_remaining)


def score_waiver_candidates(
    candidates: list[WaiverCandidate],
    close_categories: frozenset[str],
    roster_zscores: list[dict[str, float]],
    punt: frozenset[str] = frozenset(),
    limit: int = 25,
) -> tuple[WaiverScore, ...]:
    """Rank free-agent candidates by projected value to this roster this
    week.

    Category weight = need_weights(roster_zscores, punt)[cat] + (
    CLOSE_CATEGORY_WEIGHT if cat is close else 0.0), and THEN punted
    categories are forced back to exactly 0.0 -- punt beats closeness. A
    category the user has deliberately conceded is not worth winning even if
    the matchup happens to be close in it right now; without this
    re-zeroing step a punted-but-close category would sneak weight back in
    via the close bonus and undermine the punt the user explicitly chose.

    Score = sum over CATEGORIES of weight[cat] *
    engine.contribution.scaled_contribution(cat, rate) * games_remaining --
    tov's scaled contribution is negative (see module docstring), so a
    high-turnover candidate is penalized, not rewarded; every category's
    contribution is scaled (not raw), so a numerically bigger category can't
    out-rank a numerically smaller one purely on unit size (see
    engine.contribution module docstring point 2).

    Returns an empty tuple, not an arbitrary ranking, when there is no basis
    to rank on (no candidates, or every category weight is 0 -- nothing
    close and no need anywhere), OR when nothing survives the worth-it gate:
    a candidate whose total score is at or below zero is dropped (see
    engine.contribution.is_worth_it). Either way, a ranking with no basis --
    or no candidate actually worth recommending -- is worse than none, and
    the caller/UI can say so explicitly rather than present a misleading
    list.
    """
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")

    valid_categories = set(CATEGORIES)
    unknown_close = close_categories - valid_categories
    if unknown_close:
        raise ValueError(f"unknown close category: {sorted(unknown_close)}")

    for candidate in candidates:
        if candidate.games_remaining < 0:
            raise ValueError(
                f"games_remaining must be >= 0 for {candidate.player_key}, "
                f"got {candidate.games_remaining}"
            )
        unknown_rate = set(candidate.rates) - valid_categories
        if unknown_rate:
            raise ValueError(
                f"unknown category in rates for {candidate.player_key}: {sorted(unknown_rate)}"
            )

    # need_weights validates punt itself (raises "unknown punt category: [...]"),
    # so no separate punt check is needed here.
    weights = dict(need_weights(roster_zscores, punt))
    for cat in CATEGORIES:
        if cat in close_categories:
            weights[cat] += CLOSE_CATEGORY_WEIGHT
    # punt beats close: re-zero AFTER the close bonus (see docstring above)
    for cat in punt:
        weights[cat] = 0.0

    if not candidates or all(w == 0.0 for w in weights.values()):
        return ()

    # threshold for the "schedule_driven" reason token: a candidate's
    # games_remaining stands out as the explanation for their rank only when
    # it clears the batch's own mean by a full game (SCHEDULE_EDGE_GAMES),
    # computed once over the full input (not the post-limit slice) so the
    # signal doesn't shift depending on `limit`
    mean_games = sum(c.games_remaining for c in candidates) / len(candidates)
    schedule_edge_threshold = mean_games + SCHEDULE_EDGE_GAMES

    scored: list[WaiverScore] = []
    for candidate in candidates:
        score = sum(
            weights[cat] * scaled_contribution(cat, candidate.rates.get(cat, 0.0))
            * candidate.games_remaining
            for cat in CATEGORIES
        )
        if not is_worth_it(score):
            # C2: a candidate contributing nothing, or actively hurting the
            # categories they're scored against, is never a recommendation
            # -- skip rather than rank them (see module docstring and
            # engine.contribution.is_worth_it; engine.streaming applies the
            # identical gate)
            continue
        categories_helped = tuple(
            cat
            for cat in CATEGORIES
            if _helps_category(
                cat, weights[cat], candidate.rates.get(cat, 0.0), candidate.games_remaining
            )
        )
        reasons = tuple(category_reason_token(cat) for cat in categories_helped)
        if candidate.games_remaining >= schedule_edge_threshold:
            reasons += (REASON_SCHEDULE_DRIVEN,)
        if candidate.stat_basis == _SEASON_AVERAGE_BASIS:
            reasons += (REASON_SEASON_AVERAGE_FALLBACK,)
        scored.append(
            WaiverScore(
                player_key=candidate.player_key,
                score=score,
                games_remaining=candidate.games_remaining,
                categories_helped=categories_helped,
                stat_basis=candidate.stat_basis,
                reasons=reasons,
            )
        )

    # score descending, then player_key ascending for a total, deterministic order
    scored.sort(key=lambda s: (-s.score, s.player_key))
    return tuple(scored[:limit])
