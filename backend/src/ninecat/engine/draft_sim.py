"""Pure pick recommender and snake mock-draft simulator.

No DB access and no dependency on ninecat.models, exactly like zscores.py,
build_profile.py, draft.py and punt.py — callers adapt their own rows into
DraftPoolPlayer before calling in. The simulator uses only random.Random(seed)
(never the global random module or wall-clock) so a given seed reproduces an
identical DraftResult every run.
"""

from __future__ import annotations

import random
from bisect import bisect_left
from dataclasses import dataclass

from ninecat.engine.draft import DraftPoolPlayer, LeagueConfig, compute_draft_values
from ninecat.engine.zscores import CATEGORIES

# display labels for the recommender's "Fills your X need" reason strings, in
# CATEGORIES order (fg_pct, ft_pct, tpm, pts, reb, ast, stl, blk, tov). Must
# match frontend/components/dashboard/categoryKeys.ts's CATEGORIES labels
# exactly (stl -> "STL", not "ST") -- that file is the single source of truth
# for label<->contract-key translation on the frontend side of this boundary.
_CATEGORY_LABELS: dict[str, str] = {
    "fg_pct": "FG%",
    "ft_pct": "FT%",
    "tpm": "3PM",
    "pts": "PTS",
    "reb": "REB",
    "ast": "AST",
    "stl": "STL",
    "blk": "BLK",
    "tov": "TO",
}

# opponent picks favor the top of the (jittered) ADP list but aren't purely
# rational — weights taper fast so upsets are rare but possible, per D3
_OPPONENT_PICK_WEIGHTS: tuple[int, ...] = (8, 4, 2, 1, 1)


def picks_until_next_turn(overall_pick: int, num_teams: int) -> int:
    """How many opponent picks happen before my next turn, in a standard
    snake draft, given `overall_pick` (1-based) is MY current pick.

    Derivation: a team at slot p (1-based) picking in round r (1-based) sits
    at overall_pick = (r-1)*num_teams + p if r is odd, or
    (r-1)*num_teams + (num_teams - p + 1) if r is even (round reversed).
    Recover (r, p) from overall_pick, then compute p's overall_pick in round
    r+1 using the same formula with the parity flipped, and subtract.
    """
    round_num = (overall_pick - 1) // num_teams + 1
    position_in_round = overall_pick - (round_num - 1) * num_teams
    if round_num % 2 == 1:
        slot = position_in_round
        # next round (r+1) is even -> reversed order
        next_overall = round_num * num_teams + (num_teams - slot + 1)
    else:
        slot = num_teams - position_in_round + 1
        # next round (r+1) is odd -> forward order
        next_overall = round_num * num_teams + slot
    return next_overall - overall_pick - 1


def snake_order(num_teams: int, rounds: int) -> tuple[int, ...]:
    """1-based team index making each overall pick, snake-ordered (even
    rounds reversed)."""
    order: list[int] = []
    for round_num in range(1, rounds + 1):
        teams = range(1, num_teams + 1)
        if round_num % 2 == 0:
            teams = reversed(teams)
        order.extend(teams)
    return tuple(order)


@dataclass(frozen=True)
class PickRecommendation:
    """One ranked pick candidate: its draft value, the need-weighted rank
    score it was sorted by, the raw contract-key categories it fills a need
    in (canonical order, UI composes its own labels from these), and the
    deterministic reason strings ready to render as-is."""

    player_key: str
    value: float
    rank_score: float
    reasons: tuple[str, ...]
    need_cats: tuple[str, ...]


def _need_weights(
    my_players: list[DraftPoolPlayer], punt: frozenset[str]
) -> dict[str, float]:
    """Per-category need weight from the roster's mean z: 0.5 for a clear
    weakness, 0.25 for a mild one, 0.0 otherwise. An empty roster has no
    basis for need, so every weight is 0 (falls through to pure value
    ranking). Punted categories are always 0 regardless of roster mean —
    fixing a punted weakness is not a real need."""
    if not my_players:
        return {cat: 0.0 for cat in CATEGORIES}
    roster_mean = {
        cat: sum(p.zscores[cat] for p in my_players) / len(my_players) for cat in CATEGORIES
    }
    weights: dict[str, float] = {}
    for cat in CATEGORIES:
        if cat in punt:
            weights[cat] = 0.0
        elif roster_mean[cat] <= -0.35:
            weights[cat] = 0.5
        elif roster_mean[cat] < 0:
            weights[cat] = 0.25
        else:
            weights[cat] = 0.0
    return weights


def _need_cats(player: DraftPoolPlayer, weights: dict[str, float]) -> tuple[str, ...]:
    """Up to 2 needed categories (weight > 0) this player's own z clears the
    0.5 fill threshold for, in canonical CATEGORIES order."""
    cats: list[str] = []
    for cat in CATEGORIES:
        if weights[cat] > 0 and player.zscores[cat] >= 0.5:
            cats.append(cat)
        if len(cats) == 2:
            break
    return tuple(cats)


def _comparable_or_better_count(sorted_ascending_values: list[float], value: float) -> int:
    """How many available players share this player's best_class and have
    value >= `value` (this player included). bisect_left on an ascending
    list finds the first index whose value is >= the target, so everything
    from that index on qualifies -- O(log n) instead of a per-player scan."""
    idx = bisect_left(sorted_ascending_values, value)
    return len(sorted_ascending_values) - idx


def _reasons(
    player: DraftPoolPlayer,
    need_cats: tuple[str, ...],
    comparable_or_better: int,
    picks_left: int,
) -> tuple[str, ...]:
    """Deterministic reason strings in spec order: (a) up to 2 need-fit
    reasons (from need_cats), (b) a fallback if none applied, (c) injury
    risk, (d) scarcity urgency."""
    reasons: list[str] = [f"Fills your {_CATEGORY_LABELS[cat]} need" for cat in need_cats]
    if not reasons:
        reasons.append("Best player available")

    games_factor = max(min(player.projected_games / 82.0, 1.0), 0.0)
    if games_factor < 0.75:
        reasons.append(f"Injury risk: {int(player.projected_games)} games")

    # "few better options remain at your position": count only players AT
    # LEAST as good as this one (comparable-or-better), not every positive-
    # value player in the class -- the latter fired for nearly the whole
    # pool on a real draft board (reviewed finding), since most of a deep
    # position is positive-value even though only a handful are genuinely
    # competing with any single player's own tier
    if comparable_or_better <= picks_left:
        reasons.append("May not last until your next pick")

    return tuple(reasons)


def recommend_picks(
    my_players: list[DraftPoolPlayer],
    available: list[DraftPoolPlayer],
    config: LeagueConfig,
    overall_pick: int,
    punt: frozenset[str] = frozenset(),
    limit: int = 5,
) -> list[PickRecommendation]:
    """Rank the top `limit` available players for the pick at `overall_pick`.

    Valuation is recomputed over `available` (the remaining pool) each call
    so replacement levels — and therefore scarcity — evolve as the draft
    progresses (D3/D6). rank_score adds a need-weighted z bonus on top of
    raw draft value so a scarce need can outrank a slightly higher-value
    player at a position of strength.
    """
    values = compute_draft_values(available, config, punt)
    weights = _need_weights(my_players, punt)

    # per-class values, sorted ascending once, so each player's own
    # comparable-or-better count is a bisect instead of an O(n) scan
    class_values: dict[str, list[float]] = {}
    for dv in values.values():
        class_values.setdefault(dv.best_class, []).append(dv.value)
    for lst in class_values.values():
        lst.sort()

    picks_left = picks_until_next_turn(overall_pick, config.num_teams)

    recs = []
    for p in available:
        dv = values[p.player_key]
        rank_score = dv.value + sum(p.zscores[c] * weights[c] for c in CATEGORIES)
        need_cats = _need_cats(p, weights)
        comparable_or_better = _comparable_or_better_count(class_values[dv.best_class], dv.value)
        recs.append(
            PickRecommendation(
                player_key=p.player_key,
                value=dv.value,
                rank_score=rank_score,
                reasons=_reasons(p, need_cats, comparable_or_better, picks_left),
                need_cats=need_cats,
            )
        )

    # rank_score desc; ties -> player_key ascending, so ordering (and
    # therefore the simulator's picks) is fully deterministic
    recs.sort(key=lambda r: (-r.rank_score, r.player_key))
    return recs[:limit]


@dataclass(frozen=True)
class DraftResult:
    """One completed mock draft: every pick in order, plus a convenience
    view of the drafting user's own roster."""

    picks: tuple[tuple[int, int, str], ...]
    my_roster: tuple[str, ...]


def simulate_draft(
    pool: list[DraftPoolPlayer],
    config: LeagueConfig,
    my_slot: int,
    rounds: int,
    seed: int,
    adp: list[str] | None = None,
    punt: frozenset[str] = frozenset(),
) -> DraftResult:
    """Run a full snake mock draft. My picks use recommend_picks against the
    live remaining pool; opponent picks sample the top of the (remaining)
    ADP list with a single seeded RNG created once up front, so the same
    seed always reproduces an identical DraftResult (no wall clock, no
    global random state).
    """
    # a pool shorter than the draft needs silently truncates: fewer picks
    # get made, my_roster comes back short, and nothing signals why -- loud
    # failure beats a quietly incomplete draft (reviewed finding)
    required = config.num_teams * rounds
    if len(pool) < required:
        raise ValueError(
            f"pool has {len(pool)} players, need at least {required} "
            f"for {config.num_teams} teams x {rounds} rounds"
        )

    by_key = {p.player_key: p for p in pool}

    if adp is None:
        # default ADP = full-pool value desc, no punt (D3) -- a punt is a
        # *my-roster* strategy, not an assumption about how the field drafts
        base_values = compute_draft_values(pool, config)
        adp_keys = [p.player_key for p in sorted(
            pool, key=lambda p: (-base_values[p.player_key].value, p.player_key)
        )]
    else:
        # an adp that doesn't cover exactly the pool desyncs the two "who's
        # still available" views the loop below relies on: a pool player
        # missing from adp silently starves the opponent branch (dry-ADP
        # break) while the player still sits in `pool`/`available`, and an
        # adp key not in the pool gets drafted as a phantom pick (taken.add
        # and picks.append both accept it uncritically) -- both fail loudly
        # here instead (reviewed finding)
        adp_keys_set = set(adp)
        pool_keys_set = set(by_key)
        if adp_keys_set != pool_keys_set:
            missing = sorted(pool_keys_set - adp_keys_set)
            extra = sorted(adp_keys_set - pool_keys_set)
            raise ValueError(
                f"adp must contain exactly the pool's player keys; "
                f"missing={missing} extra={extra}"
            )
        adp_keys = list(adp)

    order = snake_order(config.num_teams, rounds)
    rng = random.Random(seed)
    taken: set[str] = set()
    remaining_adp = list(adp_keys)
    my_players: list[DraftPoolPlayer] = []
    picks: list[tuple[int, int, str]] = []
    my_roster: list[str] = []

    for i, team in enumerate(order):
        overall_pick = i + 1
        if team == my_slot:
            available = [p for p in pool if p.player_key not in taken]
            if not available:
                break
            top = recommend_picks(my_players, available, config, overall_pick, punt, limit=1)
            chosen_key = top[0].player_key
        else:
            candidates = remaining_adp[: min(5, len(remaining_adp))]
            if not candidates:
                break
            weights = _OPPONENT_PICK_WEIGHTS[: len(candidates)]
            chosen_key = rng.choices(candidates, weights=weights, k=1)[0]

        taken.add(chosen_key)
        if chosen_key in remaining_adp:
            remaining_adp.remove(chosen_key)
        picks.append((overall_pick, team, chosen_key))
        if team == my_slot:
            my_players.append(by_key[chosen_key])
            my_roster.append(chosen_key)

    return DraftResult(picks=tuple(picks), my_roster=tuple(my_roster))
