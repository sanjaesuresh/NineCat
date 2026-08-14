"""Marcel-style baseline per-game projection: recency-weighted rates, regressed
toward the position-group mean by sample size, then aged.

Every later projection layer (role/usage adjustments in Task 7, composite
scoring after that) starts from this baseline, so it stays pure/deterministic
(no I/O) and keeps percentage stats as makes+attempts rather than bare
percentages, matching SeasonLine's own convention.
"""

from __future__ import annotations

from dataclasses import dataclass

from nineproj.config import AgeCurve, Settings
from nineproj.data.nba_stats import SeasonLine
from nineproj.data.universe import PlayerRecord

# the 11 per-game counting/shooting stats every rate/blend operates over
STAT_FIELDS: tuple[str, ...] = (
    "fgm", "fga", "ftm", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov",
)

# volume stats the age curve multiplies directly; fgm/ftm are rebuilt from
# pct * (aged) attempts instead, so makes can never exceed attempts (step 7)
_VOLUME_STATS: tuple[str, ...] = (
    "fga", "fta", "tpm", "pts", "reb", "ast", "stl", "blk", "tov",
)

_POSITION_GROUPS: tuple[str, ...] = ("guard", "forward", "center", "all")

# first-letter-of-position -> population group; anything else (incl. None,
# blank, or a code like "PG") falls back to the "all" population mean
_LETTER_TO_GROUP: dict[str, str] = {"G": "guard", "F": "forward", "C": "center"}


def _position_group(position: str | None) -> str:
    """Map a SeasonLine/PlayerRecord position string to its population group.

    Hyphenated multi-position strings ("Forward-Center") use only the first
    letter, so they land in their primary group rather than being unmapped.
    """
    if not position or not position.strip():
        return "all"
    letter = position.strip()[0].upper()
    return _LETTER_TO_GROUP.get(letter, "all")


@dataclass(frozen=True)
class PopulationContext:
    """Per-minute mean rate for each stat, by position group ("all" = everyone)."""

    group_rates: dict[str, dict[str, float]]


@dataclass(frozen=True)
class BaselineProjection:
    """One player's projected per-game line before role/usage adjustments (Task 7)."""

    minutes: float
    games: int | None  # games projection belongs to the availability model; always None here
    fgm: float
    fga: float
    ftm: float
    fta: float
    tpm: float
    pts: float
    reb: float
    ast: float
    stl: float
    blk: float
    tov: float
    sample_size_score: float
    seasons_used: list[str]


def build_population_context(
    lines_by_season: dict[str, list[SeasonLine]], settings: Settings
) -> PopulationContext:
    """Position-group mean per-minute rates from the most recent season present.

    Weighted by games x minutes so heavy-minutes players dominate the mean the
    way they'll dominate real fantasy outcomes; a line with minutes<=0 or
    games<=0 can't produce a rate and is skipped.
    """
    group_rates: dict[str, dict[str, float]] = {
        group: dict.fromkeys(STAT_FIELDS, 0.0) for group in _POSITION_GROUPS
    }
    if not lines_by_season:
        return PopulationContext(group_rates=group_rates)

    latest_season = max(lines_by_season)
    weighted_sums = {group: dict.fromkeys(STAT_FIELDS, 0.0) for group in _POSITION_GROUPS}
    weight_totals = dict.fromkeys(_POSITION_GROUPS, 0.0)

    for line in lines_by_season[latest_season]:
        if line.minutes <= 0 or line.games <= 0:
            continue
        weight = line.games * line.minutes
        # every line counts toward its own group AND the universal "all" mean
        for target_group in {_position_group(line.position), "all"}:
            weight_totals[target_group] += weight
            for stat in STAT_FIELDS:
                weighted_sums[target_group][stat] += weight * (getattr(line, stat) / line.minutes)

    for group in _POSITION_GROUPS:
        total = weight_totals[group]
        if total > 0:
            group_rates[group] = {
                stat: weighted_sums[group][stat] / total for stat in STAT_FIELDS
            }
    return PopulationContext(group_rates=group_rates)


def _age_multiplier(age: float, curve: AgeCurve) -> float:
    """Volume-stat multiplier from the age curve, clamped to [floor, ceiling]."""
    if age < curve.improve_until:
        multiplier = 1 + curve.young_bonus * (curve.improve_until - age)
    elif curve.decline_after < age <= curve.steep_decline_after:
        multiplier = 1 - curve.old_penalty * (age - curve.decline_after)
    elif age > curve.steep_decline_after:
        multiplier = (
            1
            - curve.old_penalty * (curve.steep_decline_after - curve.decline_after)
            - curve.steep_penalty * (age - curve.steep_decline_after)
        )
    else:
        multiplier = 1.0
    return max(curve.multiplier_floor, min(curve.multiplier_ceiling, multiplier))


def project_baseline(
    player: PlayerRecord,
    history: dict[str, SeasonLine],
    context: PopulationContext,
    settings: Settings,
) -> BaselineProjection | None:
    """Recency-weighted, regressed, aged per-game baseline for one player.

    Returns None when the player has no usable season (every prior season
    missing, or every present one has minutes<=0/games<=0) -- there is no
    rate to blend from, so callers must treat that as "no baseline" rather
    than a zeroed-out projection.
    """
    blend_weights = settings.baseline.blend_weights
    usable = [
        (season, history[season], blend_weight)
        for season, blend_weight in zip(settings.prior_seasons, blend_weights)
        if season in history and history[season].minutes > 0 and history[season].games > 0
    ]
    if not usable:
        return None

    # step 1-2: per-minute rate per season, blended weight = blend_weight * games * minutes
    rate_weight_total = 0.0
    blended_rate = dict.fromkeys(STAT_FIELDS, 0.0)
    sample = 0.0
    minutes_weight_total = 0.0
    minutes_weighted_sum = 0.0

    for _season, line, blend_weight in usable:
        season_sample = line.games * line.minutes
        sample += season_sample
        rate_weight = blend_weight * season_sample
        rate_weight_total += rate_weight
        for stat in STAT_FIELDS:
            blended_rate[stat] += rate_weight * (getattr(line, stat) / line.minutes)

        # minutes blend uses its own weight (games only, no sample/minutes term)
        minutes_weight = blend_weight * line.games
        minutes_weight_total += minutes_weight
        minutes_weighted_sum += minutes_weight * line.minutes

    if rate_weight_total > 0:
        blended_rate = {stat: value / rate_weight_total for stat, value in blended_rate.items()}

    # step 3: sample-size score and step 4: regression toward the group mean
    sample_size_score = min(1.0, sample / settings.baseline.full_sample_minutes)
    shrink = settings.baseline.regression_strength * (1 - sample_size_score)
    group_mean = context.group_rates[_position_group(player.position)]
    final_rate = {
        stat: (1 - shrink) * blended_rate[stat] + shrink * group_mean[stat]
        for stat in STAT_FIELDS
    }

    # step 5: minutes projection, blended by games (role adjustments come in Task 7)
    projected_minutes = (
        minutes_weighted_sum / minutes_weight_total if minutes_weight_total > 0 else 0.0
    )

    # step 7 (computed before the age multiplier touches attempts): shooting
    # consistency ratios from the regressed rate, so makes stay tied to attempts
    fg_pct = final_rate["fgm"] / final_rate["fga"] if final_rate["fga"] > 0 else 0.0
    ft_pct = final_rate["ftm"] / final_rate["fta"] if final_rate["fta"] > 0 else 0.0

    # step 6: age multiplier on volume rates only, not fgm/ftm directly
    age_multiplier = _age_multiplier(player.age, settings.baseline.age_curve)
    aged_rate = dict(final_rate)
    for stat in _VOLUME_STATS:
        aged_rate[stat] = final_rate[stat] * age_multiplier

    # rebuild makes from pct * (now-aged) attempts, then clamp as a safety net
    # against floating-point creep so makes can never exceed attempts
    aged_rate["fgm"] = min(fg_pct * aged_rate["fga"], aged_rate["fga"])
    aged_rate["ftm"] = min(ft_pct * aged_rate["fta"], aged_rate["fta"])

    # step 8: per-game stats = final per-minute rates x projected minutes
    per_game = {stat: aged_rate[stat] * projected_minutes for stat in STAT_FIELDS}

    return BaselineProjection(
        minutes=projected_minutes,
        games=None,
        sample_size_score=sample_size_score,
        seasons_used=[season for season, _line, _weight in usable],
        **per_game,
    )
