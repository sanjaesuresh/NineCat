"""Pure draft valuation engine: base z-total, positional scarcity (VORP),
games-played risk, and punt-aware re-valuation.

No DB access and no dependency on ninecat.models, exactly like zscores.py and
build_profile.py — callers adapt their own draftable-pool rows into
DraftPoolPlayer, so this stays testable and storage-agnostic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ninecat.engine.positions import SLOT_CLASSES, slot_classes
from ninecat.engine.zscores import CATEGORIES

# the five slots demand/replacement/vorp are computed against; "G"/"F" are
# composite slots that feed PG+SG / SF+PF respectively rather than standing
# alone, and "UTIL" is a pseudo-class used only as a fallback (see below)
BASE_POSITIONS = ("PG", "SG", "SF", "PF", "C")

# fallback slot-class for players with no base-position eligibility at all
# (unknown/None position) -- their replacement is drawn from the whole pool
UTIL_CLASS = "UTIL"

# composite slot each base position draws half-weight starter demand from
# (PG/SG share the generic "G" slot, SF/PF share "F"); C has none
_COMPOSITE_SLOT: dict[str, str | None] = {
    "PG": "G", "SG": "G", "SF": "F", "PF": "F", "C": None,
}

# standard Yahoo 9-cat roster layout, used as the default LeagueConfig.roster_slots
DEFAULT_ROSTER_SLOTS: tuple[tuple[str, int], ...] = (
    ("PG", 1), ("SG", 1), ("G", 1), ("SF", 1), ("PF", 1), ("F", 1),
    ("C", 2), ("UTIL", 3), ("BN", 3), ("IL", 2),
)


@dataclass(frozen=True)
class DraftPoolPlayer:
    """One draftable player: their raw category z-scores (tov already inverted
    upstream by compute_player_zscores) plus the inputs valuation needs."""

    player_key: str
    position: str | None
    projected_games: float
    zscores: dict[str, float]


@dataclass(frozen=True)
class LeagueConfig:
    num_teams: int
    roster_slots: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class DraftValue:
    base: float
    vorp: float
    value: float
    best_class: str
    replacement: float


def _slot_counts(roster_slots: tuple[tuple[str, int], ...]) -> dict[str, int]:
    """Sum counts per slot name (duplicates allowed in the input); BN/IL and
    any other unrecognized names simply never get looked up below, so they're
    implicitly ignored rather than needing an explicit skip-list."""
    counts: dict[str, int] = {}
    for name, count in roster_slots:
        counts[name] = counts.get(name, 0) + count
    return counts


def _demand(position: str, num_teams: int, counts: dict[str, int]) -> int:
    """Starter demand for one base position (or the UTIL pseudo-class),
    rounded UP -- a fractional starter slot still means real competition for
    that spot, so it must never be rounded away."""
    if position == UTIL_CLASS:
        raw = num_teams * counts.get("UTIL", 0)
    else:
        composite = _COMPOSITE_SLOT[position]
        composite_count = counts.get(composite, 0) if composite else 0
        raw = num_teams * (
            counts.get(position, 0) + composite_count / 2 + counts.get("UTIL", 0) / 5
        )
    return math.ceil(raw)


def _replacement_level(
    base_by_key: dict[str, float], eligible_keys: list[str], demand: int
) -> float:
    """Base of the (demand+1)-th best eligible player (0-indexed: `demand`),
    or the worst eligible player if the pool is shallower than that; 0.0 if
    nobody is eligible at all."""
    if not eligible_keys:
        return 0.0
    ordered = sorted(eligible_keys, key=lambda k: base_by_key[k], reverse=True)
    index = min(demand, len(ordered) - 1)
    return base_by_key[ordered[index]]


def compute_draft_values(
    players: list[DraftPoolPlayer],
    config: LeagueConfig,
    punt: frozenset[str] = frozenset(),
) -> dict[str, DraftValue]:
    """Per-player draft value: base z-sum (punt-aware), positional scarcity
    (VORP against a starter-demand replacement level), and games-played risk.
    `value` is pure value-over-replacement (VORP scaled by games share) -- it
    can be negative for a below-replacement player, by design (D4). `base`
    and `replacement` are carried on DraftValue as display data, not folded
    into `value`. See engine/draft.py module docstring / test_draft.py for
    the exact formula each step follows.
    """
    unknown = punt - set(CATEGORIES)
    if unknown:
        raise ValueError(f"unknown punt category: {sorted(unknown)}")
    if config.num_teams < 1:
        raise ValueError(f"LeagueConfig.num_teams must be >= 1, got {config.num_teams}")
    counts = _slot_counts(config.roster_slots)
    # if roster_slots recognizes no starter slot at all (e.g. empty, or only
    # BN/IL/typo'd names), every demand computes to 0 -> replacement anchors
    # to each class's BEST player instead of a real replacement level,
    # silently inverting cross-class ordering rather than raising -- caught
    # here instead. (The API layer maps empty settings_json to
    # DEFAULT_ROSTER_SLOTS before building the config, so this only fires on
    # a genuine caller bug.)
    if not any(counts.get(name, 0) > 0 for name in SLOT_CLASSES):
        raise ValueError(
            "LeagueConfig.roster_slots must include at least one recognized "
            f"starter slot ({', '.join(SLOT_CLASSES)}); got {config.roster_slots}"
        )
    if not players:
        return {}

    included_cats = [c for c in CATEGORIES if c not in punt]

    base_by_key = {p.player_key: sum(p.zscores[c] for c in included_cats) for p in players}
    classes_by_key = {p.player_key: slot_classes(p.position) for p in players}
    all_keys = [p.player_key for p in players]

    # replacement levels are shared across every player competing for a given
    # class, so compute each class once rather than recomputing per player
    replacement_by_class: dict[str, float] = {}
    for pos in BASE_POSITIONS:
        # iterate the fixed all_keys list and test frozenset MEMBERSHIP only
        # (`pos in classes_by_key[k]`) -- never iterate a frozenset itself
        # here. frozenset iteration order is hash-randomized per process
        # (PYTHONHASHSEED), so doing so would make eligibility order (and
        # therefore ties in _replacement_level's sort) nondeterministic
        # across runs even though it's stable within any single run
        eligible = [k for k in all_keys if pos in classes_by_key[k]]
        demand = _demand(pos, config.num_teams, counts)
        replacement_by_class[pos] = _replacement_level(base_by_key, eligible, demand)
    util_demand = _demand(UTIL_CLASS, config.num_teams, counts)
    replacement_by_class[UTIL_CLASS] = _replacement_level(base_by_key, all_keys, util_demand)

    result: dict[str, DraftValue] = {}
    for p in players:
        base = base_by_key[p.player_key]
        # iterate the fixed BASE_POSITIONS tuple (never the player's own
        # slot_classes frozenset) and test membership only, so candidate
        # order -- and therefore max()'s tie-break below -- is the same
        # canonical PG,SG,SF,PF,C order on every run regardless of hash seed,
        # independent of the order tokens happen to appear in the position
        # label (e.g. "PF-SG" must still prefer SG, pinned by a dedicated
        # tie-break test)
        candidates = [pos for pos in BASE_POSITIONS if pos in classes_by_key[p.player_key]]
        if candidates:
            # max() keeps the first tie encountered, and candidates is already
            # in BASE_POSITIONS (canonical PG,SG,SF,PF,C) order -> ties break
            # to the canonical-earliest class, per spec
            best_class, replacement = max(
                ((pos, replacement_by_class[pos]) for pos in candidates),
                key=lambda pair: base - pair[1],
            )
        else:
            # no direct/composite eligibility at all (None/unrecognized
            # position) -> fall back to the UTIL pseudo-class against the
            # whole pool rather than a position nobody could ever hold
            best_class, replacement = UTIL_CLASS, replacement_by_class[UTIL_CLASS]
        vorp = base - replacement

        # a player who might not suit up only delivers their surplus-over-
        # replacement in proportion to how much of the season they play; a
        # missed season contributes zero vorp, not a replacement-level floor
        # (D4: value is pure VORP, so it can go negative for a below-
        # replacement player -- games risk shrinks toward 0, not toward
        # replacement)
        games_factor = max(min(p.projected_games / 82.0, 1.0), 0.0)
        value = vorp * games_factor

        result[p.player_key] = DraftValue(
            base=base, vorp=vorp, value=value, best_class=best_class, replacement=replacement,
        )
    return result
