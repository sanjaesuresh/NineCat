// Mirrors the shape written by projections/src/nineproj/export/dataset.py
// (_player_json / build_dataset) field-for-field. Keep this file in sync with
// that module -- it is the single source of truth for the export schema.

/** The 9 fantasy scoring categories, matching ninecat's category keys. */
export type CategoryKey =
  | "fg_pct"
  | "ft_pct"
  | "tpm"
  | "pts"
  | "reb"
  | "ast"
  | "stl"
  | "blk"
  | "tov";

export interface Projection {
  games: number;
  minutes: number;
  points: number;
  rebounds: number;
  assists: number;
  steals: number;
  blocks: number;
  three_pm: number;
  fg_pct: number;
  ft_pct: number;
  turnovers: number;
  fga: number;
  fta: number;
  fgm: number;
  ftm: number;
}

export interface Fantasy {
  per_game_zscores: Record<CategoryKey, number>;
  per_game_value: number;
  // nineproj.value.ninecat.PlayerValue computes this per-category breakdown
  // (mirrors per_game_zscores but off season-totals z's), but dataset.py's
  // export doesn't emit it yet -- optional so the type stays honest about the
  // currently-shipped payload; punt-build (lib/puntBuild.ts) degrades
  // gracefully (skips the availability-adjusted swap) when it's absent.
  availability_adjusted_zscores?: Record<CategoryKey, number>;
  availability_adjusted_value: number;
  regular_season_value: number;
  // null exactly when schedule_available is false (mirrors Schedule's null fields)
  playoff_value: number | null;
  combined_value: number;
  final_score: number;
  punt_values: Record<CategoryKey, number>;
  scarcity_score: number;
}

export type InjuryRiskLabel = "low" | "moderate" | "high";

export interface Availability {
  raw_projected_games: number;
  injury_adjusted_games: number;
  injury_risk_score: number;
  injury_risk_label: InjuryRiskLabel;
  availability_probability: number;
}

export type RoleDirection = "positive" | "negative" | "neutral";

export interface Role {
  role_change_score: number;
  direction: RoleDirection;
  minutes_delta: number;
  usage_delta: number;
  minutes_projection: number;
  // no evidence source distinguishes projected starters from bench players (dataset.py)
  starter_probability: number | null;
  team_changed: boolean;
  pace_multiplier: number;
}

/** One candidate playoff-window's precomputed schedule + value fields (e.g.
 * "18-20") -- same null convention as Schedule's top-level fields: all-None
 * exactly when that window's schedule data is unavailable. */
export interface WindowProfile {
  week_games: Record<string, number> | null;
  playoff_games: number | null;
  playoff_b2bs: number | null;
  playoff_schedule_score: number | null;
  expected_playoff_games: number | null;
  playoff_value_z: number | null;
}

export interface Schedule {
  // null exactly when schedule_available is false (D6 branch, dataset.py);
  // always equal to windows[<the shipped default_window>]'s own entry
  week_games: Record<string, number> | null;
  playoff_games: number | null;
  playoff_b2bs: number | null;
  playoff_schedule_score: number | null;
  expected_playoff_games: number | null;
  // one entry per Dataset.candidate_windows, keyed by window label ("17-19"..)
  windows: Record<string, WindowProfile>;
}

export interface ConsensusPerSource {
  rank: number;
  imputed: boolean;
}

export type DisagreementFlag =
  | "no_consensus"
  | "high_uncertainty"
  | "model_loves"
  | "model_fades"
  | "none";

export interface Consensus {
  consensus_rank: number | null;
  sources_used: number;
  rank_variance: number | null;
  per_source: Record<string, ConsensusPerSource>;
  rank_difference: number | null;
  flag: DisagreementFlag;
}

/** The 8 composite component keys (settings.composite_weights field names). */
export type ComponentKey =
  | "per_game"
  | "availability_adjusted"
  | "expected_games"
  | "role_usage"
  | "playoff_schedule"
  | "consensus"
  | "team_environment"
  | "category_scarcity";

export type ConfidenceBand = "HIGH" | "MEDIUM" | "LOW";

export interface Model {
  model_rank: number;
  final_rank: number;
  confidence: number;
  confidence_band: ConfidenceBand;
  // null per component the player lacks (e.g. no consensus, no schedule)
  component_scores: Record<ComponentKey, number | null>;
  // dataset.py omits a key entirely (rather than nulling it) for a component
  // the player lacks -- Partial (not a total Record) says so at the type level
  component_contributions: Partial<Record<ComponentKey, number>>;
}

export interface Analysis {
  strengths: string[];
  risks: string[];
  explanation: string;
}

export type SourceType = "statistical_model" | "expert_rank" | "projection" | "adp" | "community_rank" | "news";

export interface PlayerSource {
  source: string;
  url: string;
  retrieved: string;
  type: SourceType;
}

export interface Player {
  rank: number;
  player_id: string;
  name: string;
  team: string;
  positions: string[];
  age: number | null;
  projection: Projection;
  fantasy: Fantasy;
  availability: Availability;
  role: Role;
  schedule: Schedule;
  consensus: Consensus;
  model: Model;
  analysis: Analysis;
  sources: PlayerSource[];
}

// --- settings.json (nineproj.config.Settings.model_dump()) ---

export interface CompositeWeights {
  per_game: number;
  availability_adjusted: number;
  expected_games: number;
  role_usage: number;
  playoff_schedule: number;
  consensus: number;
  team_environment: number;
  category_scarcity: number;
}

export interface ValueSplit {
  regular_season: number;
  playoff: number;
}

export interface PlayoffWindow {
  start_week: number;
  end_week: number;
}

export interface SourceTypeWeights {
  statistical_model: number;
  expert_rank: number;
  projection: number;
  adp: number;
  community_rank: number;
  news: number;
}

export interface QualityTierWeights {
  very_high: number;
  high: number;
  medium_high: number;
  medium: number;
  low_medium: number;
  low: number;
}

export interface ConsensusSettings {
  source_type_weights: SourceTypeWeights;
  quality_tier_weights: QualityTierWeights;
  disagreement_rank_threshold: number;
  high_variance_threshold: number;
  imputation_penalty: number;
}

export interface AgeCurve {
  improve_until: number;
  decline_after: number;
  steep_decline_after: number;
  young_bonus: number;
  old_penalty: number;
  steep_penalty: number;
  multiplier_floor: number;
  multiplier_ceiling: number;
}

export interface Baseline {
  blend_weights: [number, number, number];
  regression_strength: number;
  full_sample_minutes: number;
  min_rankable_minutes: number;
  age_curve: AgeCurve;
}

export interface AdjustmentCaps {
  minutes_delta: number;
  usage_delta: number;
  pace_multiplier: number;
}

export interface RiskThresholds {
  low: number;
  moderate: number;
}

export interface AgePenalties {
  under_28: number;
  from_28_to_31: number;
  from_32_to_34: number;
  over_34: number;
}

export interface AvailabilitySettings {
  risk_thresholds: RiskThresholds;
  league_median_games: number;
  regression_games: number;
  shrink_factor: number;
  missed_share_weight: number;
  chronic_penalty: number;
  current_injury_risk_cap: number;
  age_penalties: AgePenalties;
}

export interface ConfidenceBands {
  high: number;
  medium: number;
}

export interface ConfidenceWeights {
  sample: number;
  injury: number;
  role: number;
  source_agreement: number;
}

export interface Cache {
  ttl_hours: number;
}

export interface GamesBounds {
  min: number;
  max: number;
}

export interface Settings {
  season: string;
  prior_seasons: [string, string, string];
  composite_weights: CompositeWeights;
  value_split: ValueSplit;
  playoff_window: PlayoffWindow;
  fantasy_week1_start: string;
  consensus: ConsensusSettings;
  baseline: Baseline;
  adjustment_caps: AdjustmentCaps;
  availability: AvailabilitySettings;
  confidence_bands: ConfidenceBands;
  confidence_weights: ConfidenceWeights;
  cache: Cache;
  games_bounds: GamesBounds;
  scarcity_z_threshold: number;
}

export interface Dataset {
  season: string;
  projection_date: string;
  last_updated: string;
  settings: Settings;
  schedule_available: boolean;
  // true only for the "schedule fetched but its playoff window has zero
  // games league-wide" case (a partial/early-release NBA schedule) --
  // distinct from schedule_available=false meaning "no schedule fetched at all"
  playoff_window_force_unavailable: boolean;
  // dashboard dropdown options ("17-19".."22-24") and the pipeline's shipped
  // default (derived from settings.playoff_window, not hardcoded)
  candidate_windows: string[];
  default_window: string;
  players: Player[];
}
