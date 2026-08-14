"""Pure add-schedule (streaming) optimizer: given a weekly add budget and a
set of category-close free-agent candidates, pick which player to add on
which remaining day to buy the most games in the categories the matchup is
actually close in. Punted categories are excluded from that set even when
the matchup reads them as close (see plan_streaming's docstring).

No DB access and no dependency on ninecat.models, exactly like zscores.py and
punt.py -- callers (the Task 7 matchup endpoint) adapt their own roster/
schedule rows into StreamCandidate before calling in. No clock, no
randomness: the remaining-week window and today's already-used adds are the
caller's responsibility, passed in as start_day/end_day/adds_available.

This module owns only WHEN to add someone (day and budget assignment). The
sign rule, per-category scaling, worth-it gate, and "helps X" rule all live
in engine.contribution and are shared verbatim with engine.waivers (which
owns HOW to present the ranked list) -- see that module's docstring for the
reasoning behind each. Two modules answering "which free agent helps me this
week" must never independently reinvent, and disagree on, the same rules.

Every StreamSlot.reason and StreamPlan.notes entry is a structured contract
token, never English prose -- the frontend composes the sentence (see
components/dashboard/categoryKeys.ts). Emitting prose here was a review
finding on two earlier tasks; do not repeat it.

Reason token vocabulary (StreamSlot.reason):
  "category:<key>"  -- one per category in `categories_helped`, contract key
                        from engine.zscores.CATEGORIES (e.g. "category:pts").
                        Same helps-a-category rule as engine.waivers (see
                        engine.contribution.helps_category): a positive raw
                        rate for every category except tov, which requires a
                        LOW raw rate (< engine.contribution.LOW_TOV_RATE) AND
                        games_added > 0 -- a candidate who adds turnovers, or
                        who does not play, is never tagged as helping tov.
  "back_to_back"     -- this slot's day is the first of a back-to-back for
                        this player (their next calendar day also has a game
                        that `games_added` already counts), the concrete
                        reason a back-to-back day outranks a one-game day

Note token vocabulary (StreamPlan.notes), one per early-return, never raised:
  "no_candidates"             -- candidates was empty
  "no_close_categories"       -- close_categories, AFTER removing punted
                        categories, was empty (an all-punted close set is
                        the same as no close set: nothing left to stream for)
  "no_adds_available"         -- adds_available <= 0
  "invalid_window"            -- start_day > end_day
  "no_games_in_window"        -- candidates and close categories were both
                        real, but not one candidate had a game inside
                        [start_day, end_day] -- distinct from "no_candidates"
                        so the UI can say why the plan is empty rather than
                        rendering a silently-empty slots list; adds_reserved
                        is always 0 in this case (see plan_streaming's
                        docstring -- a plan with nothing to schedule never
                        reports a reservation)
  "no_positive_value_remaining" -- budget and candidates remained, but the
                        best (day, candidate) pair left was worth <= 0 (e.g.
                        turnover cost outweighing counting-stat gain); the
                        plan stops rather than recommend a scarce add that
                        would actively hurt the categories it claims to chase
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ninecat.engine.contribution import (
    category_reason_token,
    helps_category,
    is_worth_it,
    scaled_contribution,
)
from ninecat.engine.zscores import CATEGORIES

_ONE_DAY = timedelta(days=1)

NOTE_NO_CANDIDATES = "no_candidates"
NOTE_NO_CLOSE_CATEGORIES = "no_close_categories"
NOTE_NO_ADDS_AVAILABLE = "no_adds_available"
NOTE_INVALID_WINDOW = "invalid_window"
NOTE_NO_GAMES_IN_WINDOW = "no_games_in_window"
NOTE_NO_POSITIVE_VALUE_REMAINING = "no_positive_value_remaining"

REASON_BACK_TO_BACK = "back_to_back"


@dataclass(frozen=True)
class StreamCandidate:
    """One streamable free agent: their per-game category rates and the
    dates they play within the remaining window (caller pre-filters to the
    window, but plan_streaming re-clips defensively)."""

    player_key: str
    game_dates: tuple[date, ...]
    category_rates: dict[str, float]


@dataclass(frozen=True)
class StreamSlot:
    """One recommended add: which player, on which day, and how many
    additional games (from that day through the window's end) it buys."""

    day: date
    player_key: str
    games_added: int
    # canonical CATEGORIES-order subset of close_categories this pick
    # actually contributes a positive rate to
    categories_helped: tuple[str, ...]
    reason: tuple[str, ...]


@dataclass(frozen=True)
class StreamPlan:
    slots: tuple[StreamSlot, ...]
    adds_used: int
    adds_reserved: int
    notes: tuple[str, ...]


def _empty(notes: tuple[str, ...]) -> StreamPlan:
    return StreamPlan(slots=(), adds_used=0, adds_reserved=0, notes=notes)


def plan_streaming(
    candidates: list[StreamCandidate],
    close_categories: frozenset[str],
    start_day: date,
    end_day: date,
    adds_available: int,
    reserve_last_day: bool = True,
    punt: frozenset[str] = frozenset(),
) -> StreamPlan:
    """Greedily assign the weekly add budget to (day, candidate) pairs, best
    value first. A pick's value only counts categories in `close_categories
    - punt` -- a category already locked earns nothing here (the entire
    point of the feature, see module docstring / plan doc M5), and neither
    does a category the user has deliberately punted, even when the matchup
    currently reads it as close (punt beats close, mirroring
    engine.waivers.score_waiver_candidates exactly).

    A candidate's value is the sum, over every un-punted close category, of
    engine.contribution.scaled_contribution(cat, rate) * games this pick
    would buy -- scaled, not raw, so a numerically bigger category (points)
    can't out-rank a numerically smaller one (steals) purely on unit size
    (see engine.contribution module docstring point 2).

    M6: a candidate's own earliest in-window game date always weakly
    dominates every later date of theirs (value only grows as the day moves
    earlier, since more of their remaining games get counted), so there is
    exactly one (day, candidate) entry per candidate here, not one per
    (day, candidate) pair -- the day dimension was dead generality.

    See module docstring for the exact reason/note token vocabulary; see
    test_streaming.py for hand-computed value examples.
    """
    valid_categories = set(CATEGORIES)
    unknown_close = close_categories - valid_categories
    if unknown_close:
        raise ValueError(f"unknown close category: {sorted(unknown_close)}")
    unknown_punt = punt - valid_categories
    if unknown_punt:
        raise ValueError(f"unknown punt category: {sorted(unknown_punt)}")
    for candidate in candidates:
        unknown_rate = set(candidate.category_rates) - valid_categories
        if unknown_rate:
            raise ValueError(
                f"unknown category in category_rates for {candidate.player_key}: "
                f"{sorted(unknown_rate)}"
            )

    # punt beats close: re-derive AFTER validating both sets, exactly the
    # ordering engine.waivers uses for its own weight re-zero
    effective_close = close_categories - punt

    # ordinary states the UI must render, not caller bugs -- never raise here
    if not candidates:
        return _empty((NOTE_NO_CANDIDATES,))
    if not effective_close:
        return _empty((NOTE_NO_CLOSE_CATEGORIES,))
    if adds_available <= 0:
        return _empty((NOTE_NO_ADDS_AVAILABLE,))
    if start_day > end_day:
        return _empty((NOTE_INVALID_WINDOW,))

    # one entry per candidate (M6 -- see docstring): day is always their
    # earliest in-window game date, games_added counts every in-window game
    # from that date onward. Iterate CATEGORIES (never effective_close
    # itself) so the sum order -- and therefore float accumulation -- is
    # stable across runs regardless of frozenset hash-iteration order
    entries: list[tuple[date, str, float, int, tuple[str, ...], bool]] = []
    for candidate in candidates:
        dates_in_window = sorted(d for d in candidate.game_dates if start_day <= d <= end_day)
        if not dates_in_window:
            continue
        dates_set = set(dates_in_window)
        day = dates_in_window[0]
        games_added = len(dates_in_window)
        value = sum(
            scaled_contribution(cat, candidate.category_rates.get(cat, 0.0)) * games_added
            for cat in CATEGORIES
            if cat in effective_close
        )
        categories_helped = tuple(
            cat
            for cat in CATEGORIES
            if cat in effective_close
            and helps_category(cat, candidate.category_rates.get(cat, 0.0), games_added)
        )
        # "back-to-back" means adding today also captures tomorrow's
        # game, which games_added already reflects -- this only marks
        # the FIRST day of the pair, not the second (adding on the
        # second day has already missed the first game)
        is_back_to_back = (day + _ONE_DAY) in dates_set
        entries.append((day, candidate.player_key, value, games_added, categories_helped, is_back_to_back))

    if not entries:
        # I4: candidates and close categories were both real, but nobody has
        # a game in the window -- a distinct, honest note, not a silently
        # empty plan (and no reservation was ever spent, see below)
        return _empty((NOTE_NO_GAMES_IN_WINDOW,))

    # hold one add back for the final day, UNLESS that would leave nothing to
    # plan at all (adds_available <= 1) -- the reservation must never starve
    # the plan down to empty
    adds_reserved = 1 if reserve_last_day and adds_available > 1 else 0
    budget = adds_available - adds_reserved

    slots: list[StreamSlot] = []
    used_players: set[str] = set()
    remaining_budget = budget
    stopped_for_no_positive_value = False
    while remaining_budget > 0:
        candidates_left = [e for e in entries if e[1] not in used_players]
        if not candidates_left:
            break
        # highest value wins; ties break by earliest day, then player_key --
        # folded into one key so a single min() is fully deterministic (no
        # set/dict iteration order involved). games_added is no longer part
        # of the tie-break: with one entry per candidate, two entries can
        # only tie in value with different games_added by coincidence of
        # differently-scaled categories, which day/player_key already breaks
        # deterministically -- a dedicated games_added tie-break was dead
        # code (M6) once the day dimension collapsed.
        day, player_key, value, games_added, categories_helped, is_back_to_back = min(
            candidates_left, key=lambda e: (-e[2], e[0], e[1])
        )
        if not is_worth_it(value):
            # the single best remaining option is worthless or actively
            # harmful (e.g. its turnover cost outweighs its counting-stat
            # gain) -- a real manager stops streaming here rather than spend
            # a scarce add on a pick that hurts the categories it targets
            stopped_for_no_positive_value = True
            break
        reason = tuple(category_reason_token(cat) for cat in categories_helped)
        if is_back_to_back:
            reason += (REASON_BACK_TO_BACK,)
        slots.append(
            StreamSlot(
                day=day,
                player_key=player_key,
                games_added=games_added,
                categories_helped=categories_helped,
                reason=reason,
            )
        )
        used_players.add(player_key)
        remaining_budget -= 1

    notes = (NOTE_NO_POSITIVE_VALUE_REMAINING,) if stopped_for_no_positive_value else ()
    return StreamPlan(
        slots=tuple(slots), adds_used=len(slots), adds_reserved=adds_reserved, notes=notes
    )
