"""Trade evaluation: before/after build profiles for both sides of a proposed
trade, plus a verdict from MY perspective (T4 in the trade-analyzer plan).

No DB access and no dependency on ninecat.models, exactly like roster_compare.py
and trade_candidates.py -- built entirely on RosterPlayer/TradeCandidate.

VALUE YARDSTICK: net_value is the delta, on MY side, of the raw category-total
sum compute_team_profile already produces ("totals" summed across all 9
categories). The plan (T3) prefers the draft engine's value-over-replacement
(vorp) as a scarcity-aware yardstick, but evaluate_trade's only inputs are the
two rosters and the candidate -- RosterPlayer carries no position, and there is
no draftable-pool argument here for compute_draft_values to rank against.
Computing "vorp" against a substitute pool assembled from just these two
13-ish-man rosters would make replacement level swing on irrelevant bench
players rather than reflect real league-wide scarcity -- exactly the kind of
approximation this module's dependencies (see trade_candidates.py) explicitly
avoid. So net_value uses the same totals the before/after profiles already
show, keeping the number the UI renders always internally consistent with the
profile panels next to it. `config` is still accepted and defaulted (from
DEFAULT_ROSTER_SLOTS) per the contract, reserved for a future position-aware
yardstick once RosterPlayer carries position data.

REASON TOKEN VOCABULARY (structured, never English prose -- the UI composes
the wording):
  "gained:<category>"    -- MY post-trade per-category MEAN z rose by more
                            than MATERIAL_MEAN_DELTA.
  "lost:<category>"      -- MY post-trade per-category MEAN z fell by more
                            than MATERIAL_MEAN_DELTA.
  "collapsed:<category>" -- category was labelled "strong" on MY roster
                            pre-trade and is not "strong" post-trade.
  "no_downside"           -- MY lost and collapsed tuples are both empty;
                            emitted explicitly so the UI always has something
                            to render in the downside slot.
  "rejected"               -- the verdict is "rejected" (a collapse on MY side
                            overrides the value math); the collapsed
                            category/ies are still named via "collapsed:*".
"""

from __future__ import annotations

from dataclasses import dataclass

from ninecat.engine.build_profile import compute_team_profile
from ninecat.engine.draft import DEFAULT_ROSTER_SLOTS, LeagueConfig
from ninecat.engine.roster_compare import RosterPlayer
from ninecat.engine.trade_candidates import MATERIAL_MEAN_DELTA, TradeCandidate
from ninecat.engine.zscores import CATEGORIES

# within +/- this band of net_value, a trade reads as "balanced" rather than
# clearly favoring either side -- exported so the UI can render the same band
BALANCED_NET_VALUE = 0.5

# sensible fallback league shape when the caller has no real settings synced
# yet, mirroring api/routes.py's own LeagueConfig fallback (num_teams=12)
_DEFAULT_NUM_TEAMS = 12


@dataclass(frozen=True)
class SideOutcome:
    """One side's build profile before and after a proposed trade."""

    before: dict  # compute_team_profile result pre-trade
    after: dict  # compute_team_profile result post-trade
    gained: tuple[str, ...]  # categories materially improved, canonical order
    lost: tuple[str, ...]  # categories materially worsened, canonical order
    collapsed: tuple[str, ...]  # "strong" pre-trade, not "strong" post-trade


@dataclass(frozen=True)
class TradeVerdict:
    candidate: TradeCandidate
    mine: SideOutcome
    theirs: SideOutcome
    net_value: float  # my post-trade minus pre-trade total, my yardstick
    verdict: str  # "favors_me" | "favors_them" | "balanced" | "rejected"
    reasons: tuple[str, ...]  # structured contract-key tokens


def _default_config() -> LeagueConfig:
    return LeagueConfig(num_teams=_DEFAULT_NUM_TEAMS, roster_slots=DEFAULT_ROSTER_SLOTS)


def _swap_rosters(
    candidate: TradeCandidate, mine: list[RosterPlayer], theirs: list[RosterPlayer]
) -> tuple[list[RosterPlayer], list[RosterPlayer]]:
    """Actually swap the named players and return the two post-trade rosters.
    No delta approximation -- the same rule trade_candidates.py follows,
    because these rosters are small enough that approximating is how this
    kind of tool gets subtly wrong."""
    mine_by_key = {p.player_key: p for p in mine}
    theirs_by_key = {p.player_key: p for p in theirs}

    missing_give = [key for key in candidate.give if key not in mine_by_key]
    if missing_give:
        raise ValueError(f"trade 'give' player(s) not found on mine roster: {missing_give}")
    missing_get = [key for key in candidate.get if key not in theirs_by_key]
    if missing_get:
        raise ValueError(f"trade 'get' player(s) not found on theirs roster: {missing_get}")

    give_keys = set(candidate.give)
    get_keys = set(candidate.get)
    new_mine = [p for p in mine if p.player_key not in give_keys] + [
        theirs_by_key[key] for key in candidate.get
    ]
    new_theirs = [p for p in theirs if p.player_key not in get_keys] + [
        mine_by_key[key] for key in candidate.give
    ]
    return new_mine, new_theirs


def _side_outcome(pre: list[RosterPlayer], post: list[RosterPlayer]) -> SideOutcome:
    """Recompute compute_team_profile on both the pre- and actually-swapped
    post-trade roster. gained/lost compare the PER-CATEGORY MEAN z (total /
    roster size) against MATERIAL_MEAN_DELTA, so float noise never reads as
    movement -- the same guard trade_candidates.py applies. collapsed is the
    honesty check: any category "strong" before and not "strong" after."""
    before = compute_team_profile([dict(p.zscores) for p in pre])
    after = compute_team_profile([dict(p.zscores) for p in post])
    pre_size = len(pre)
    post_size = len(post)

    gained = []
    lost = []
    collapsed = []
    for cat in CATEGORIES:
        pre_mean = (before["totals"][cat] / pre_size) if pre_size else 0.0
        post_mean = (after["totals"][cat] / post_size) if post_size else 0.0
        delta = post_mean - pre_mean
        if delta > MATERIAL_MEAN_DELTA:
            gained.append(cat)
        elif delta < -MATERIAL_MEAN_DELTA:
            lost.append(cat)
        if before["labels"][cat] == "strong" and after["labels"][cat] != "strong":
            collapsed.append(cat)

    return SideOutcome(
        before=before,
        after=after,
        gained=tuple(gained),
        lost=tuple(lost),
        collapsed=tuple(collapsed),
    )


def _reasons_for(mine_outcome: SideOutcome, rejected: bool) -> tuple[str, ...]:
    reasons = [f"gained:{cat}" for cat in mine_outcome.gained]
    reasons += [f"lost:{cat}" for cat in mine_outcome.lost]
    reasons += [f"collapsed:{cat}" for cat in mine_outcome.collapsed]
    # the downside slot must never be silently empty -- see module docstring
    if not mine_outcome.lost and not mine_outcome.collapsed:
        reasons.append("no_downside")
    if rejected:
        reasons.append("rejected")
    return tuple(reasons)


def evaluate_trade(
    candidate: TradeCandidate,
    mine: list[RosterPlayer],
    theirs: list[RosterPlayer],
    config: LeagueConfig | None = None,
) -> TradeVerdict:
    """Evaluate one proposed trade from MY perspective. Builds the real
    post-trade rosters (never a delta approximation) and re-runs
    compute_team_profile on each side."""
    if config is None:
        config = _default_config()

    new_mine, new_theirs = _swap_rosters(candidate, mine, theirs)
    mine_outcome = _side_outcome(mine, new_mine)
    theirs_outcome = _side_outcome(theirs, new_theirs)

    net_value = sum(mine_outcome.after["totals"].values()) - sum(
        mine_outcome.before["totals"].values()
    )

    # a trade that collapses a category I was winning is never a good trade,
    # even when the value math likes it -- overrides the net_value thresholds
    if mine_outcome.collapsed:
        verdict = "rejected"
    elif net_value > BALANCED_NET_VALUE:
        verdict = "favors_me"
    elif net_value < -BALANCED_NET_VALUE:
        verdict = "favors_them"
    else:
        verdict = "balanced"

    reasons = _reasons_for(mine_outcome, rejected=verdict == "rejected")

    return TradeVerdict(
        candidate=candidate,
        mine=mine_outcome,
        theirs=theirs_outcome,
        net_value=net_value,
        verdict=verdict,
        reasons=reasons,
    )


def evaluate_trades(
    candidates: list[TradeCandidate],
    mine: list[RosterPlayer],
    theirs: list[RosterPlayer],
    config: LeagueConfig | None = None,
    limit: int = 10,
) -> tuple[TradeVerdict, ...]:
    """Evaluate a batch of candidates and return them sorted best-for-me
    first (highest net_value), tie-broken by the candidate's give then get
    tuples for determinism."""
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")

    verdicts = [evaluate_trade(c, mine, theirs, config=config) for c in candidates]
    verdicts.sort(key=lambda v: (-v.net_value, v.candidate.give, v.candidate.get))
    return tuple(verdicts[:limit])
