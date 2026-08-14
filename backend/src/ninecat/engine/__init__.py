from ninecat.engine.build_profile import PUNT_MEAN_Z, STRONG_MEAN_Z, compute_team_profile
from ninecat.engine.contribution import (
    CATEGORY_SCALE,
    LOW_TOV_RATE,
    TOV_CATEGORY,
    category_reason_token,
    helps_category,
    is_worth_it,
    scaled_contribution,
    signed_contribution,
)
from ninecat.engine.draft import (
    DEFAULT_ROSTER_SLOTS,
    DraftPoolPlayer,
    DraftValue,
    LeagueConfig,
    compute_draft_values,
)
from ninecat.engine.draft_sim import (
    DraftResult,
    PickRecommendation,
    picks_until_next_turn,
    recommend_picks,
    simulate_draft,
    snake_order,
)
from ninecat.engine.matchup import (
    CLOSE_MARGIN_ABS_PCT,
    CLOSE_MARGIN_RATIO,
    CategoryVerdict,
    MatchupComparison,
    compare_matchup,
)
from ninecat.engine.needs import NEED_MILD_Z, NEED_STRONG_Z, need_weights
from ninecat.engine.positions import SLOT_CLASSES, slot_classes
from ninecat.engine.punt import PuntSuggestion, suggest_punt_builds
from ninecat.engine.roster_compare import (
    FRAGILE_SHARE,
    MEANINGFUL_Z,
    CategoryStrength,
    RosterComparison,
    RosterPlayer,
    compare_rosters,
)
from ninecat.engine.streaming import (
    NOTE_INVALID_WINDOW,
    NOTE_NO_ADDS_AVAILABLE,
    NOTE_NO_CANDIDATES,
    NOTE_NO_CLOSE_CATEGORIES,
    NOTE_NO_GAMES_IN_WINDOW,
    NOTE_NO_POSITIVE_VALUE_REMAINING,
    REASON_BACK_TO_BACK,
    StreamCandidate,
    StreamPlan,
    StreamSlot,
    plan_streaming,
)
from ninecat.engine.trade_candidates import (
    MATERIAL_MEAN_DELTA,
    CandidateSet,
    TradeCandidate,
    generate_trade_candidates,
)
from ninecat.engine.trade_eval import (
    BALANCED_NET_VALUE,
    SideOutcome,
    TradeVerdict,
    evaluate_trade,
    evaluate_trades,
)
from ninecat.engine.waivers import (
    CLOSE_CATEGORY_WEIGHT,
    REASON_SCHEDULE_DRIVEN,
    REASON_SEASON_AVERAGE_FALLBACK,
    SCHEDULE_EDGE_GAMES,
    WaiverCandidate,
    WaiverScore,
    score_waiver_candidates,
)
from ninecat.engine.weekly import WeeklyPlayerRate, WeeklyProjection, project_week
from ninecat.engine.zscores import CATEGORIES, PlayerAverages, compute_player_zscores

# single frontend-facing catalog of every reason/note token either free-agent
# scorer (engine.streaming, engine.waivers) can emit, so the UI has one place
# to map token -> copy instead of two independently-drifting lists. Built
# here (not in engine.contribution) because it needs both modules' own
# tokens, and engine.contribution must not import either of them (they
# import it). See engine.contribution's module docstring for why streaming
# and waivers must agree on this vocabulary in the first place.
REASON_TOKENS: frozenset[str] = frozenset(
    {category_reason_token(cat) for cat in CATEGORIES}
    | {REASON_BACK_TO_BACK, REASON_SCHEDULE_DRIVEN, REASON_SEASON_AVERAGE_FALLBACK}
)
NOTE_TOKENS: frozenset[str] = frozenset(
    {
        NOTE_NO_CANDIDATES,
        NOTE_NO_CLOSE_CATEGORIES,
        NOTE_NO_ADDS_AVAILABLE,
        NOTE_INVALID_WINDOW,
        NOTE_NO_GAMES_IN_WINDOW,
        NOTE_NO_POSITIVE_VALUE_REMAINING,
    }
)

__all__ = [
    "BALANCED_NET_VALUE",
    "CATEGORIES",
    "CATEGORY_SCALE",
    "CLOSE_CATEGORY_WEIGHT",
    "CLOSE_MARGIN_ABS_PCT",
    "CLOSE_MARGIN_RATIO",
    "DEFAULT_ROSTER_SLOTS",
    "FRAGILE_SHARE",
    "LOW_TOV_RATE",
    "MATERIAL_MEAN_DELTA",
    "MEANINGFUL_Z",
    "NEED_MILD_Z",
    "NEED_STRONG_Z",
    "NOTE_INVALID_WINDOW",
    "NOTE_NO_ADDS_AVAILABLE",
    "NOTE_NO_CANDIDATES",
    "NOTE_NO_CLOSE_CATEGORIES",
    "NOTE_NO_GAMES_IN_WINDOW",
    "NOTE_NO_POSITIVE_VALUE_REMAINING",
    "NOTE_TOKENS",
    "PUNT_MEAN_Z",
    "REASON_BACK_TO_BACK",
    "REASON_SCHEDULE_DRIVEN",
    "REASON_SEASON_AVERAGE_FALLBACK",
    "REASON_TOKENS",
    "SCHEDULE_EDGE_GAMES",
    "SLOT_CLASSES",
    "STRONG_MEAN_Z",
    "TOV_CATEGORY",
    "CandidateSet",
    "CategoryStrength",
    "CategoryVerdict",
    "DraftPoolPlayer",
    "DraftResult",
    "DraftValue",
    "LeagueConfig",
    "MatchupComparison",
    "PickRecommendation",
    "PlayerAverages",
    "PuntSuggestion",
    "RosterComparison",
    "RosterPlayer",
    "SideOutcome",
    "StreamCandidate",
    "StreamPlan",
    "StreamSlot",
    "TradeCandidate",
    "TradeVerdict",
    "WaiverCandidate",
    "WaiverScore",
    "WeeklyPlayerRate",
    "WeeklyProjection",
    "category_reason_token",
    "compare_matchup",
    "compare_rosters",
    "compute_draft_values",
    "compute_player_zscores",
    "compute_team_profile",
    "evaluate_trade",
    "evaluate_trades",
    "generate_trade_candidates",
    "helps_category",
    "is_worth_it",
    "need_weights",
    "picks_until_next_turn",
    "plan_streaming",
    "project_week",
    "recommend_picks",
    "scaled_contribution",
    "score_waiver_candidates",
    "signed_contribution",
    "simulate_draft",
    "slot_classes",
    "snake_order",
    "suggest_punt_builds",
]
