"""Fixed engine scenarios for the REAL cross-process determinism guard (see
test_cross_process_determinism.py). Each `scenario_*` function below builds a
literal input (deliberately tie-prone -- several candidates/categories score
exactly equal, so a tie-break actually has to fire) and returns the engine's
full ordered output as a JSON-serializable object.

This module is invoked as a subprocess by direct file path (`python
cross_process_scenarios.py <name>`, see test_cross_process_determinism.py),
once per PYTHONHASHSEED under test, so it must be import-safe with no
DB/network/env dependency -- pure engine calls only, mirroring the in-process
determinism tests these scenarios are drawn from (see each function's
docstring for its source test). NOTE: `python -m tests.cross_process_scenarios`
would be the more obvious invocation, but yahoo_fantasy_api ships its own
top-level "tests" package in site-packages that shadows this one (and is
itself broken to import) -- direct-path invocation sidesteps that collision.

Inputs deliberately mix multi-key dicts and multi-key frozensets, since those
are exactly the containers whose iteration order is hash-seed-dependent --
the class of bug an in-process double-call can never observe (one process,
one seed for its whole lifetime).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import date

from ninecat.engine.draft import DraftPoolPlayer, LeagueConfig, compute_draft_values
from ninecat.engine.matchup import compare_matchup
from ninecat.engine.punt import suggest_punt_builds
from ninecat.engine.roster_compare import RosterPlayer
from ninecat.engine.streaming import StreamCandidate, plan_streaming
from ninecat.engine.trade_candidates import TradeCandidate
from ninecat.engine.trade_eval import evaluate_trades
from ninecat.engine.waivers import WaiverCandidate, score_waiver_candidates
from ninecat.engine.weekly import WeeklyProjection
from ninecat.engine.zscores import CATEGORIES


def _to_jsonable(obj):
    """Recursively convert engine output to something json.dumps can eat.

    frozensets are converted via sorted() -- a frozenset has no meaningful
    iteration order by definition (that's the whole reason these engines
    carry a separate canonical-order tuple field, e.g. PuntSuggestion.
    punt_ordered), so sorting it here is not masking anything; the thing
    actually under test is the ORDER OF LISTS/TUPLES the engine produced,
    which this function passes through untouched, and dict key order, which
    is preserved (dict insertion order is real signal: a dict built by
    iterating a set internally would leak hash-seed order right here).
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, frozenset):
        return sorted(_to_jsonable(x) for x in obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def _z(**overrides: float) -> dict[str, float]:
    z = {c: 0.0 for c in CATEGORIES}
    z.update(overrides)
    return z


DAY1 = date(2024, 1, 1)
DAY2 = date(2024, 1, 2)
DAY3 = date(2024, 1, 3)
DAY4 = date(2024, 1, 4)


def scenario_streaming_plan():
    """Mirrors test_streaming.py::test_identical_inputs_produce_identical_plans,
    but with a genuine 3-way value tie (alpha/charlie/delta all score exactly
    1.0 via different categories) so day/player_key tie-break order actually
    matters, plus a 4-key close_categories frozenset. echo helps two
    categories at once (reb and blk) so categories_helped's own canonical
    order is exercised too, not just the candidate ranking."""
    close = frozenset({"pts", "ast", "reb", "blk"})
    alpha = StreamCandidate(player_key="alpha", game_dates=(DAY1, DAY2), category_rates={"pts": 5.0})
    bravo = StreamCandidate(player_key="bravo", game_dates=(DAY2, DAY3), category_rates={"pts": 5.0})
    charlie = StreamCandidate(
        player_key="charlie", game_dates=(DAY1, DAY2), category_rates={"pts": 5.0, "ast": 0.0}
    )
    delta = StreamCandidate(player_key="delta", game_dates=(DAY1,), category_rates={"reb": 4.0})
    echo = StreamCandidate(
        player_key="echo", game_dates=(DAY3,), category_rates={"reb": 4.0, "blk": 1.0}
    )

    plan = plan_streaming(
        [delta, bravo, alpha, charlie, echo],
        close,
        DAY1,
        DAY4,
        adds_available=5,
        reserve_last_day=False,
    )
    return _to_jsonable(plan)


def scenario_waivers_ranking():
    """Mirrors test_waivers.py::test_tied_scores_break_by_player_key_ascending,
    extended to a 3-way tie across three different close categories (pts/
    ast/stl each scaled to the same 0.5 contribution) so ranking has to fall
    through to player_key ascending, not just a 2-way case."""
    close = frozenset({"pts", "ast", "stl"})
    zack = WaiverCandidate(player_key="zack", games_remaining=2.0, rates={"pts": 5.0}, stat_basis="projection")
    amy = WaiverCandidate(player_key="amy", games_remaining=2.0, rates={"ast": 1.5}, stat_basis="projection")
    mike = WaiverCandidate(player_key="mike", games_remaining=2.0, rates={"stl": 0.5}, stat_basis="projection")
    bob = WaiverCandidate(player_key="bob", games_remaining=2.0, rates={"pts": 1.0}, stat_basis="season_average")

    result = score_waiver_candidates([zack, amy, mike, bob], close, [])
    return _to_jsonable(result)


def scenario_punt_tie_break():
    """Verbatim test_punt.py::test_tie_break_is_deterministic_and_pinned --
    fg_pct and ft_pct roster means tie exactly, so single-category candidate
    ranking depends on canonical CATEGORIES order, not frozenset order."""
    config = LeagueConfig(num_teams=1, roster_slots=(("UTIL", 1),))
    roster = [DraftPoolPlayer(player_key="me", position=None, projected_games=82.0, zscores=_z(fg_pct=-1.0, ft_pct=-1.0))]

    suggestions = suggest_punt_builds(roster, [], config, limit=3)
    return _to_jsonable(suggestions)


def scenario_trade_eval_ordering():
    """Mirrors test_trade_eval.py::
    test_evaluate_trades_orders_best_for_me_first_with_deterministic_tie_break --
    c1/c2 tie exactly on net_value, so ordering depends on the give tuple
    tie-break, not dict/set iteration."""

    def player(key, **overrides):
        return RosterPlayer(player_key=key, zscores=_z(**overrides))

    def candidate(give, get):
        return TradeCandidate(give=give, get=get, my_gain=(), my_loss=(), their_gain=(), their_loss=())

    mine = [player("keep1"), player("gA"), player("gB")]
    theirs = [player("t1", pts=1.0), player("t2", pts=1.0), player("t3", pts=0.2)]
    c1 = candidate(give=("gA",), get=("t1",))
    c2 = candidate(give=("gB",), get=("t2",))
    c3 = candidate(give=("gA",), get=("t3",))

    result = evaluate_trades([c3, c2, c1], mine, theirs)
    return _to_jsonable(result)


def scenario_compute_draft_values():
    """Mirrors test_draft.py::test_exact_vorp_tie_breaks_to_earlier_canonical_class
    (m2 is PF-SG-eligible with a label order that would mislead a naive
    string-order tie-break) plus a punt frozenset (both punted categories are
    0.0 for every player here, so it exercises the frozenset input path
    without perturbing the pinned tie)."""
    config = LeagueConfig(num_teams=1, roster_slots=(("SG", 1), ("PF", 1)))
    punt = frozenset({"stl", "blk"})
    m2 = DraftPoolPlayer(player_key="m2", position="PF-SG", projected_games=82.0, zscores=_z(pts=6.0))
    sg_low = DraftPoolPlayer(player_key="sg_low", position="SG", projected_games=82.0, zscores=_z(pts=2.0))
    pf_low = DraftPoolPlayer(player_key="pf_low", position="PF", projected_games=82.0, zscores=_z(pts=2.0))

    values = compute_draft_values([m2, sg_low, pf_low], config, punt=punt)
    return {key: _to_jsonable(value) for key, value in values.items()}


def scenario_matchup_comparison():
    """compare_matchup with several dead-even (tie) and narrowly-close
    categories at once, so `focus`'s stable sort has real ties to resolve on
    top of the genuinely close ones (mirrors test_matchup.py::
    test_comparison_is_deterministic_across_repeated_calls's shape, widened
    for more simultaneous close/tie categories)."""

    def projection(**totals):
        base = {cat: 0.0 for cat in CATEGORIES}
        base.update(totals)
        return WeeklyProjection(
            totals=base,
            components={"fgm": 0.0, "fga": 0.0, "ftm": 0.0, "fta": 0.0},
            games=3.0,
            player_games={},
        )

    # pts/reb/ast/stl: exact ties (45-45 style, nonzero combined -> "close" flip targets)
    # blk/tov: narrow non-tied margins, also within the "close" band
    mine = projection(pts=100.0, reb=45.0, ast=20.0, stl=8.0, blk=5.2, tov=15.0, fg_pct=0.5, ft_pct=0.8, tpm=10.0)
    theirs = projection(pts=100.0, reb=45.0, ast=20.0, stl=8.0, blk=5.0, tov=15.2, fg_pct=0.5, ft_pct=0.8, tpm=10.0)

    result = compare_matchup(mine, theirs)
    return _to_jsonable(result)


SCENARIOS = {
    "streaming_plan": scenario_streaming_plan,
    "waivers_ranking": scenario_waivers_ranking,
    "punt_tie_break": scenario_punt_tie_break,
    "trade_eval_ordering": scenario_trade_eval_ordering,
    "compute_draft_values": scenario_compute_draft_values,
    "matchup_comparison": scenario_matchup_comparison,
}


if __name__ == "__main__":
    name = sys.argv[1]
    # sort_keys=False: dict key order is real signal here, see _to_jsonable
    print(json.dumps(SCENARIOS[name](), sort_keys=False))
