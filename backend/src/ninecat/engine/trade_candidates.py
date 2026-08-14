"""Trade candidate generation: pairs a roster's tradeable surplus against the
other roster's tradeable surplus, and keeps only packages that plausibly help
both sides without collapsing either team's build.

No DB access and no dependency on ninecat.models, exactly like roster_compare.py
and draft.py -- this stays pure/testable, built entirely on RosterComparison.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from ninecat.engine.roster_compare import (
    MEANINGFUL_Z,
    CategoryStrength,
    RosterComparison,
    RosterPlayer,
    compare_rosters,
)
from ninecat.engine.zscores import CATEGORIES

# a per-category MEAN z move smaller than this is reported as unchanged --
# guards my_gain/my_loss (and the both-sides-improve check, which reuses
# these sets) against flagging floating-point noise as a real swing
MATERIAL_MEAN_DELTA = 0.05

# only 1-for-1 and 2-for-2 are supported for now; uneven packages (2-for-1)
# and anything larger are out of scope per the plan -- the search space
# grows combinatorially and needs its own cap/disclosure story later
_MAX_SUPPORTED_PACKAGE = 2

# hard ceiling on how many give/get combinations are ever examined, independent
# of `limit` (which caps KEPT candidates, not evaluated ones) -- two 13-man
# rosters at max_package=2 is C(13,2)^2 = 6,084 recomputations of compare_rosters
# worst case, which is fine offline but not something an HTTP request should
# eat silently every time few candidates happen to pass the keep filter
MAX_EVALUATED = 2000


@dataclass(frozen=True)
class TradeCandidate:
    """One proposed swap. give/get are canonical-sorted player_key tuples;
    the four *_gain/*_loss tuples are in canonical CATEGORIES order and list
    only categories whose per-category MEAN z moved by more than
    MATERIAL_MEAN_DELTA when the swap is actually applied."""

    give: tuple[str, ...]
    get: tuple[str, ...]
    my_gain: tuple[str, ...]
    my_loss: tuple[str, ...]
    their_gain: tuple[str, ...]
    their_loss: tuple[str, ...]


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[TradeCandidate, ...]
    evaluated: int  # how many give/get combinations were actually examined
    truncated: bool  # True iff `limit` or MAX_EVALUATED stopped the search early


def _diff_categories(
    pre: dict[str, CategoryStrength], post: dict[str, CategoryStrength]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Per-category MEAN z delta (post - pre), split into gain/loss tuples in
    canonical CATEGORIES order. A delta within +/-MATERIAL_MEAN_DELTA counts
    as unchanged (reported in neither tuple)."""
    gain = tuple(
        cat for cat in CATEGORIES if post[cat].mean - pre[cat].mean > MATERIAL_MEAN_DELTA
    )
    loss = tuple(
        cat for cat in CATEGORIES if post[cat].mean - pre[cat].mean < -MATERIAL_MEAN_DELTA
    )
    return gain, loss


def _collapses_a_strong_category(
    pre: dict[str, CategoryStrength], post: dict[str, CategoryStrength]
) -> bool:
    """True if any category labelled "strong" before the trade is not
    labelled "strong" after it. Checked across ALL categories (not just the
    ones the trade targets) and regardless of fragility, because the guard
    exists to catch a swap that collapses a category as a side effect, not
    just the category it was built around."""
    return any(pre[cat].label == "strong" and post[cat].label != "strong" for cat in CATEGORIES)


def _combo_stream(
    eligible_give: list[RosterPlayer],
    eligible_get: list[RosterPlayer],
    package_sizes: tuple[int, ...],
):
    """Yield (give_combo, get_combo) pairs in a single deterministic order:
    package size ascending, then combinations in eligible-list order (already
    sorted by player_key). A single flat generator (rather than nested loops
    at the call site) makes the "stop once `limit` are kept" cap a plain
    early `break`, with no risk of a partial nested-loop exit."""
    for k in package_sizes:
        if k > len(eligible_give) or k > len(eligible_get):
            continue
        for give_combo in itertools.combinations(eligible_give, k):
            for get_combo in itertools.combinations(eligible_get, k):
                yield give_combo, get_combo


def generate_trade_candidates(
    mine: list[RosterPlayer],
    theirs: list[RosterPlayer],
    comparison: RosterComparison | None = None,
    max_package: int = 2,
    limit: int = 25,
    punt: frozenset[str] = frozenset(),
) -> CandidateSet:
    """Generate two-sided trade candidates between `mine` and `theirs`.

    Give players are drawn only from players who meaningfully contribute (z
    >= MEANINGFUL_Z, the same bar roster_compare uses for depth) to one of MY
    surplus categories; get players only from players who meaningfully
    contribute to one of THEIR surplus categories -- surplus already
    excludes fragile "strong" categories, so this never has to look at
    labels/fragility directly. A merely-positive-but-marginal contributor
    (below MEANINGFUL_Z) is not offered: a knowledgeable manager wouldn't
    recognise "spare a player with a 0.05 rebounding z" as using a rebounding
    surplus, and reusing MEANINGFUL_Z keeps one definition of "contributes"
    instead of two. One accepted consequence: a roster with no genuine
    (MEANINGFUL_Z-clearing) surplus depth now often yields zero candidates --
    that's honest, since it genuinely has nothing to trade from, and it
    composes with roster_compare's rule that a single-player roster's
    strengths are always fragile in the first place.

    A candidate is kept only if it moves at least one of my deficit
    categories and at least one of their deficit categories by more than
    MATERIAL_MEAN_DELTA, AND it does not collapse any category that was
    "strong" before the trade on either side. Post-trade state is always the
    real recomputed RosterComparison of the swapped rosters, never an
    approximation.

    `comparison`, if given, is trusted as-is and used instead of recomputing
    one from `mine`/`theirs` -- left None (the default) so callers don't have
    to build a matching one themselves and can't pass a stale/mismatched one
    by accident.

    `punt` names categories MY roster is deliberately conceding. comparison.my_deficit
    comes from build_profile's "punt" LABEL, which only means "de-facto weak" --
    it can't distinguish a deliberate punt from an accidental one, so without this
    a punt-build team would be required to fix the exact category it chose to punt
    (the both-sides-improve filter below rejects everything else). Punted categories
    are dropped from the deficit set this function uses for that filter and for
    ranking; comparison.my_deficit itself (and my_surplus, which punt never touches)
    is left alone since it's roster_compare's own honest read of the roster.
    """
    if max_package < 1 or max_package > _MAX_SUPPORTED_PACKAGE:
        raise ValueError(
            f"max_package must be between 1 and {_MAX_SUPPORTED_PACKAGE}, got {max_package}"
        )
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    unknown = punt - set(CATEGORIES)
    if unknown:
        raise ValueError(f"unknown punt category: {sorted(unknown)}")

    # a player can't be on both rosters -- that's a caller bug, not a trade
    dup_keys = {p.player_key for p in mine} & {p.player_key for p in theirs}
    if dup_keys:
        raise ValueError(f"player(s) appear on both rosters: {sorted(dup_keys)}")

    if comparison is None:
        comparison = compare_rosters(mine, theirs)

    # nothing to trade: no roster, no surplus to offer, or no deficit either
    # side could actually improve -- degrade to empty rather than raise
    if (
        not mine
        or not theirs
        or not comparison.my_surplus
        or not comparison.their_surplus
        or not comparison.my_deficit
        or not comparison.their_deficit
    ):
        return CandidateSet(candidates=(), evaluated=0, truncated=False)

    # deficit set the improve filter and ranking actually use: punted
    # categories are dropped since fixing them isn't a real goal. Left as the
    # bail-out above's raw comparison.my_deficit is untouched -- an all-punted
    # deficit set still means "this roster has real weak categories", it's
    # just that none of them are ones we're required to fix
    effective_my_deficit = tuple(cat for cat in comparison.my_deficit if cat not in punt)

    # sorted by player_key so combinations() (and therefore evaluation/cap
    # order) is deterministic regardless of input list order. >= MEANINGFUL_Z
    # (not just > 0): a merely-positive marginal player isn't "using a
    # surplus" -- see the function docstring
    eligible_give = sorted(
        (p for p in mine if any(p.zscores[cat] >= MEANINGFUL_Z for cat in comparison.my_surplus)),
        key=lambda p: p.player_key,
    )
    eligible_get = sorted(
        (
            p
            for p in theirs
            if any(p.zscores[cat] >= MEANINGFUL_Z for cat in comparison.their_surplus)
        ),
        key=lambda p: p.player_key,
    )

    package_sizes = (1,) if max_package == 1 else (1, 2)

    evaluated = 0
    truncated = False
    # (candidate, deficit-categories-improved count, total genuine mean
    # improvement across my non-punted deficits) -- the extra two fields are
    # the primary sort keys and are dropped once the final tuple order is set
    kept: list[tuple[TradeCandidate, int, float]] = []

    for give_combo, get_combo in _combo_stream(eligible_give, eligible_get, package_sizes):
        if evaluated >= MAX_EVALUATED:
            # hit the hard evaluation ceiling before exhausting the search
            # space (or before `limit` kept candidates were found) -- surface
            # it the same way a `limit` hit does, never silently
            truncated = True
            break
        evaluated += 1
        give_keys = {p.player_key for p in give_combo}
        get_keys = {p.player_key for p in get_combo}

        # build the swapped rosters for real and re-run compare_rosters --
        # no delta approximation, per spec, since these rosters are small
        new_mine = [p for p in mine if p.player_key not in give_keys] + list(get_combo)
        new_theirs = [p for p in theirs if p.player_key not in get_keys] + list(give_combo)
        post = compare_rosters(new_mine, new_theirs)

        my_gain, my_loss = _diff_categories(comparison.mine, post.mine)
        their_gain, their_loss = _diff_categories(comparison.theirs, post.theirs)

        improves_me = bool(set(my_gain) & set(effective_my_deficit))
        improves_them = bool(set(their_gain) & set(comparison.their_deficit))
        collapses = _collapses_a_strong_category(
            comparison.mine, post.mine
        ) or _collapses_a_strong_category(comparison.theirs, post.theirs)

        if improves_me and improves_them and not collapses:
            candidate = TradeCandidate(
                give=tuple(sorted(give_keys)),
                get=tuple(sorted(get_keys)),
                my_gain=my_gain,
                my_loss=my_loss,
                their_gain=their_gain,
                their_loss=their_loss,
            )
            deficit_improved_count = len(set(my_gain) & set(effective_my_deficit))
            # clamped to the positive part per category, NOT abs(): a trade
            # that damages one deficit category while helping another must
            # never outrank an identical trade that leaves the damaged one
            # alone -- abs() rewarded movement in either direction, which
            # means damage looked exactly like improvement to the ranking
            total_improvement = sum(
                max(0.0, post.mine[cat].mean - comparison.mine[cat].mean)
                for cat in effective_my_deficit
            )
            kept.append((candidate, deficit_improved_count, total_improvement))
            if len(kept) >= limit:
                # cap hit -- stop examining combinations and say so, never
                # silently truncate (per spec, `evaluated` still reports
                # exactly how many combinations were looked at up to here)
                truncated = True
                break

    # deterministic final order: most my-deficit categories improved first,
    # then largest total improvement, then give/get tuples as tie-breaks
    kept.sort(key=lambda t: (-t[1], -t[2], t[0].give, t[0].get))
    candidates = tuple(t[0] for t in kept)

    return CandidateSet(candidates=candidates, evaluated=evaluated, truncated=truncated)
