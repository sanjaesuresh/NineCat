"""Pure punt-build advisor: given a partial roster and the remaining draftable
pool, suggest which category (or pair of categories) to deliberately punt.

No DB access and no dependency on ninecat.models, exactly like zscores.py,
build_profile.py and draft.py — callers adapt their own rows into
DraftPoolPlayer before calling in.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from ninecat.engine.draft import DraftPoolPlayer, LeagueConfig, compute_draft_values
from ninecat.engine.zscores import CATEGORIES

# a candidate punt loses this much score per extra category beyond the first —
# dropping two weakest cats always improves the remaining-mean more than
# dropping one, so a pair must earn its extra punt rather than win by default
_SIZE_PENALTY = 0.15

# weight on the pool-value delta term relative to the roster-improvement term
_POOL_WEIGHT = 0.5

# only the top slice of the pool represents realistic future picks; averaging
# the whole remaining pool would let hundreds of irrelevant deep-bench players
# dilute the signal
_POOL_TOP_N = 10


@dataclass(frozen=True)
class PuntSuggestion:
    """One candidate punt build: the category set, its composite score, and
    the two components (roster-strength improvement, pool-value delta), plus
    the weakest punted category as a raw contract key/value (for callers to
    compose their own label, e.g. via categoryKeys.ts) and a plain-English
    rationale as a ready-to-render fallback."""

    punt: frozenset[str]
    # canonical CATEGORIES-order tuple of `punt` — the frozenset's hash-order
    # iteration is nondeterministic across runs/processes, which would make
    # JSON serialized at the API boundary flaky; this is the stable form
    punt_ordered: tuple[str, ...]
    score: float
    improvement: float
    pool_delta: float
    # weakest punted category (contract key, not prose) and its unrounded
    # roster mean z, so a caller (API/UI) can build its own label instead of
    # parsing `rationale`'s English sentence
    weakest: str
    weakest_mean: float
    rationale: str


def _top_mean(values: list[float]) -> float:
    """Mean of the top _POOL_TOP_N values (or all of them, if fewer). An
    empty pool has no basis for a delta, so 0.0 rather than raising."""
    if not values:
        return 0.0
    top = sorted(values, reverse=True)[:_POOL_TOP_N]
    return sum(top) / len(top)


def _canonical_order(punt: frozenset[str]) -> tuple[str, ...]:
    """Punted categories in canonical CATEGORIES order — the single source
    both `punt_ordered` and the tie-break key are derived from."""
    return tuple(sorted(punt, key=CATEGORIES.index))


def _order_key(punt: frozenset[str]) -> tuple[int, ...]:
    """Canonical CATEGORIES-order key for deterministic tie-breaking."""
    return tuple(CATEGORIES.index(c) for c in _canonical_order(punt))


def _weakest_and_rationale(
    punt: frozenset[str], roster_mean: dict[str, float]
) -> tuple[str, float, str]:
    """Weakest punted category (by roster mean z, canonical-order tiebreak so
    the pick stays deterministic even when two punted categories tie), its
    mean, and the plain-English sentence built from them."""
    ordered = sorted(punt, key=lambda c: (roster_mean[c], CATEGORIES.index(c)))
    weakest = ordered[0]
    weakest_mean = roster_mean[weakest]
    subject = "it" if len(ordered) == 1 else f"it and {ordered[1]}"
    rationale = (
        f"Your roster is already weak in {weakest} (mean z {weakest_mean:.2f}); "
        f"punting {subject} frees value elsewhere."
    )
    return weakest, weakest_mean, rationale


def suggest_punt_builds(
    my_players: list[DraftPoolPlayer],
    pool: list[DraftPoolPlayer],
    config: LeagueConfig,
    limit: int = 3,
) -> list[PuntSuggestion]:
    """Rank punt-build candidates for a partial roster.

    Candidates are every single category and every unordered pair drawn ONLY
    from categories where the roster is already below-average (mean z < 0) —
    punting a strength is never suggested. Each candidate is scored by how
    much the roster's remaining-category strength improves plus how much
    punt-adjusted value remains available in the pool, penalized per extra
    category punted. See module docstring / test_punt.py for the exact
    formula each component follows.
    """
    if not my_players:
        return []

    roster_mean = {
        cat: sum(p.zscores[cat] for p in my_players) / len(my_players) for cat in CATEGORIES
    }
    overall_mean = sum(roster_mean.values()) / len(CATEGORIES)

    qualifying = [c for c in CATEGORIES if roster_mean[c] < 0]
    if not qualifying:
        return []

    candidates: list[frozenset[str]] = [frozenset({c}) for c in qualifying]
    candidates += [frozenset(pair) for pair in itertools.combinations(qualifying, 2)]

    # baseline (no-punt) top-of-pool value is shared by every candidate, so
    # it's computed once rather than recomputed per candidate. Normalized
    # per-remaining-category (/9) so it's on the same scale the punted side
    # uses below -- see the per-category-normalization comment on pool_delta.
    baseline_values = [v.value for v in compute_draft_values(pool, config).values()]
    baseline_top_mean = _top_mean(baseline_values) / len(CATEGORIES)

    suggestions = []
    for punt in candidates:
        remaining = [c for c in CATEGORIES if c not in punt]
        improvement = (
            sum(roster_mean[c] for c in remaining) / len(remaining)
        ) - overall_mean

        if pool:
            # punting |S| categories means every player's base sum runs over
            # 9-|S| categories instead of 9, which mechanically shrinks pool
            # values -- and shrinks them more for a category that carries
            # more total z in the pool. An un-normalized delta therefore
            # rewards punting the LEAST impactful category, backwards from
            # the intent. Dividing each side by its own category count
            # (value-per-remaining-category) puts both sides on the same
            # scale and removes that artifact.
            punted_values = [v.value for v in compute_draft_values(pool, config, punt=punt).values()]
            pool_delta = (_top_mean(punted_values) / len(remaining)) - baseline_top_mean
        else:
            pool_delta = 0.0

        score = improvement + _POOL_WEIGHT * pool_delta - _SIZE_PENALTY * (len(punt) - 1)
        weakest, weakest_mean, rationale = _weakest_and_rationale(punt, roster_mean)

        suggestions.append(
            PuntSuggestion(
                punt=punt,
                punt_ordered=_canonical_order(punt),
                score=score,
                improvement=improvement,
                pool_delta=pool_delta,
                weakest=weakest,
                weakest_mean=weakest_mean,
                rationale=rationale,
            )
        )

    # score desc; ties -> smaller punt set first, then canonical CATEGORIES
    # order of the punted categories (both folded into the sort key so a
    # single stable sort produces the full deterministic order)
    suggestions.sort(key=lambda s: (-s.score, len(s.punt), _order_key(s.punt)))
    return suggestions[:limit]
