"""Pure weekly projection math for the NineCat engine.

This module has no DB access and no dependency on ninecat.models — like
zscores.py, it defines its own input contract (WeeklyPlayerRate) and leaves
callers (e.g. the Task 7 API layer) to adapt roster/schedule rows into it.

Scope note: this module produces raw projected TOTALS for a roster over a
date range (a fantasy week), not z-scores. In particular `tov` here is the
plain projected turnover total, NOT inverted — inversion ("lower is better")
is a comparison/verdict concern owned by the matchup module (T5), which
consumes these totals. Do not "fix" the sign here; that would double-invert
once T5 applies its own inversion.
"""

from __future__ import annotations

from dataclasses import dataclass

from ninecat.engine.zscores import CATEGORIES

# counting categories accumulated by straight rate * games; fg_pct/ft_pct are
# derived afterward from separately-accumulated makes/attempts (see project_week)
_COUNTING_FIELDS = ("tpm", "pts", "reb", "ast", "stl", "blk", "tov")


@dataclass(frozen=True)
class WeeklyPlayerRate:
    """Per-game rate for one player, plus how many games they play THIS WEEK
    (i.e. games in the fantasy-week date range being projected) — distinct
    from season games, which is what PlayerAverages.games means in zscores.py.
    """

    player_key: str
    games: float
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


@dataclass(frozen=True)
class WeeklyProjection:
    """Projected roster totals for a fantasy week.

    totals: the 9 CATEGORIES keys (fg_pct/ft_pct as ratios, the rest as sums).
    components: the raw make/attempt totals that produced fg_pct/ft_pct, kept
      around so a caller (or the UI) can see the volume behind a percentage.
    games: total roster games across the range (sum of player_games).
    player_games: games this week per player_key, so the UI can show why a
      player did or didn't contribute (e.g. 0 games -> injury/bye/rest).
    """

    totals: dict[str, float]
    components: dict[str, float]
    games: float
    player_games: dict[str, float]


def project_week(players: list[WeeklyPlayerRate]) -> WeeklyProjection:
    """Project a roster's category totals over a fantasy week.

    Counting categories are straight accumulation of rate * games. Percentages
    project makes and attempts SEPARATELY and divide once at the end — never
    average per-player percentages, which would weight a 2-attempt night the
    same as a 20-attempt one (see module docstring for the tov non-inversion
    note, and the zscores.py volume-weighting comment for the same principle
    applied to z-scores instead of totals).
    """
    for p in players:
        if p.games < 0:
            raise ValueError(f"games cannot be negative for player {p.player_key!r}")

    if not players:
        # zeroed projection, not an exception -- an empty roster is a valid
        # (if useless) input, e.g. before any players are rostered
        return WeeklyProjection(
            totals={cat: 0.0 for cat in CATEGORIES},
            components={"fgm": 0.0, "fga": 0.0, "ftm": 0.0, "fta": 0.0},
            games=0.0,
            player_games={},
        )

    # dict comprehension over the input list preserves insertion order, not
    # iteration order of any set -- keeps player_games deterministic
    player_games = {p.player_key: p.games for p in players}
    total_games = sum(player_games.values())

    counting_totals = {
        field: sum(getattr(p, field) * p.games for p in players) for field in _COUNTING_FIELDS
    }

    total_fgm = sum(p.fgm * p.games for p in players)
    total_fga = sum(p.fga * p.games for p in players)
    total_ftm = sum(p.ftm * p.games for p in players)
    total_fta = sum(p.fta * p.games for p in players)

    # guard zero attempts (e.g. a roster with no games this week) -> 0.0,
    # never a ZeroDivisionError
    fg_pct = total_fgm / total_fga if total_fga else 0.0
    ft_pct = total_ftm / total_fta if total_fta else 0.0

    totals = {
        "fg_pct": fg_pct,
        "ft_pct": ft_pct,
        **counting_totals,
    }

    return WeeklyProjection(
        totals=totals,
        components={"fgm": total_fgm, "fga": total_fga, "ftm": total_ftm, "fta": total_fta},
        games=total_games,
        player_games=player_games,
    )
