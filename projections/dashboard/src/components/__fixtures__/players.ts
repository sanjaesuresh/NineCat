import type { CategoryKey, Player } from "../../lib/types";

const ZERO_CATEGORIES: Record<CategoryKey, number> = {
  fg_pct: 0,
  ft_pct: 0,
  tpm: 0,
  pts: 0,
  reb: 0,
  ast: 0,
  stl: 0,
  blk: 0,
  tov: 0,
};

/** Neutral, fully-typed Player defaults (mirrors the pattern in
 * src/lib/recompute.test.ts) so each fixture only overrides the fields a
 * given test actually exercises. One level of nested overrides is supported
 * per section (projection/fantasy/availability/role/schedule/consensus/model). */
function basePlayer(overrides: {
  player_id: string;
  name: string;
  team: string;
  positions: string[];
  age?: number | null;
  projection?: Partial<Player["projection"]>;
  fantasy?: Partial<Player["fantasy"]>;
  availability?: Partial<Player["availability"]>;
  role?: Partial<Player["role"]>;
  schedule?: Partial<Player["schedule"]>;
  consensus?: Partial<Player["consensus"]>;
  model?: Partial<Player["model"]>;
  analysis?: Partial<Player["analysis"]>;
  sources?: Player["sources"];
}): Player {
  return {
    rank: overrides.model?.final_rank ?? 0,
    player_id: overrides.player_id,
    name: overrides.name,
    team: overrides.team,
    positions: overrides.positions,
    // `?? 25` would collapse an explicit `age: null` fixture back to 25 since
    // null is nullish -- distinguish "not provided" (undefined) from "player
    // has no known age" (explicit null) so rookie fixtures stay null.
    age: overrides.age !== undefined ? overrides.age : 25,
    projection: {
      games: 70,
      minutes: 30,
      points: 20,
      rebounds: 5,
      assists: 5,
      steals: 1,
      blocks: 1,
      three_pm: 2,
      fg_pct: 0.5,
      ft_pct: 0.8,
      turnovers: 2,
      fga: 15,
      fta: 5,
      fgm: 7,
      ftm: 4,
      ...overrides.projection,
    },
    fantasy: {
      per_game_zscores: ZERO_CATEGORIES,
      per_game_value: 0,
      availability_adjusted_value: 0,
      regular_season_value: 0,
      playoff_value: 0,
      combined_value: 0,
      final_score: 0,
      punt_values: ZERO_CATEGORIES,
      scarcity_score: 0,
      ...overrides.fantasy,
    },
    availability: {
      raw_projected_games: 70,
      injury_adjusted_games: 70,
      injury_risk_score: 0,
      injury_risk_label: "low",
      availability_probability: 1,
      ...overrides.availability,
    },
    role: {
      role_change_score: 0,
      direction: "neutral",
      minutes_delta: 0,
      usage_delta: 0,
      minutes_projection: 30,
      starter_probability: null,
      team_changed: false,
      pace_multiplier: 1,
      ...overrides.role,
    },
    schedule: {
      week_games: null,
      playoff_games: null,
      playoff_b2bs: null,
      playoff_schedule_score: null,
      expected_playoff_games: null,
      windows: {},
      ...overrides.schedule,
    },
    consensus: {
      consensus_rank: null,
      sources_used: 0,
      rank_variance: null,
      per_source: {},
      rank_difference: null,
      flag: "none",
      ...overrides.consensus,
    },
    model: {
      model_rank: 0,
      final_rank: 0,
      confidence: 50,
      confidence_band: "MEDIUM",
      component_scores: {
        per_game: 0,
        availability_adjusted: 0,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
      component_contributions: {
        per_game: 0,
        availability_adjusted: 0,
        expected_games: 0,
        role_usage: 0,
        playoff_schedule: 0,
        consensus: 0,
        team_environment: 0,
        category_scarcity: 0,
      },
      ...overrides.model,
    },
    analysis: { strengths: [], risks: [], explanation: "", ...overrides.analysis },
    sources: overrides.sources ?? [],
  };
}

/**
 * Six hand-built players covering the filter/sort/chip edge cases the Task
 * 16 test suite needs: guard vs. center positions, every injury tier, a
 * diacritic name, a rookie with null age, a big positive and a big negative
 * consensus rank_difference, a null consensus_rank (no_consensus), a null
 * playoff_schedule_score, and a team-changed / role-direction spread.
 */
export const fixturePlayers: Player[] = [
  basePlayer({
    player_id: "ace-guard",
    name: "Ace Guard",
    team: "LAL",
    positions: ["PG", "SG", "G", "UTIL"],
    age: 25,
    projection: { games: 70, minutes: 32 },
    fantasy: { per_game_value: 15.2, playoff_value: 1.5, per_game_zscores: { ...ZERO_CATEGORIES, pts: 2.4, tov: -0.6 } },
    availability: { injury_risk_label: "low" },
    consensus: { consensus_rank: 5, rank_difference: 2, flag: "none", sources_used: 3 },
    model: { final_rank: 1, confidence: 88, confidence_band: "HIGH" },
  }),
  basePlayer({
    player_id: "jokic-center",
    name: "Jokić Center",
    team: "DEN",
    positions: ["C", "UTIL"],
    age: 23,
    projection: { games: 60, minutes: 28 },
    fantasy: { per_game_value: 10.1, playoff_value: 0.8 },
    availability: { injury_risk_label: "moderate" },
    role: { team_changed: true, role_change_score: 0.1, direction: "positive" },
    consensus: { consensus_rank: 20, rank_difference: -18, flag: "model_fades", sources_used: 3 },
    model: { final_rank: 2, confidence: 65, confidence_band: "MEDIUM" },
  }),
  basePlayer({
    player_id: "forward-star",
    name: "Forward Star",
    team: "MIA",
    positions: ["SF", "PF", "F", "UTIL"],
    age: 30,
    projection: { games: 75, minutes: 34 },
    fantasy: { per_game_value: 18.5, playoff_value: 2.2 },
    availability: { injury_risk_label: "high" },
    role: { role_change_score: -0.1, direction: "negative" },
    schedule: { playoff_schedule_score: null },
    consensus: { consensus_rank: null, rank_difference: null, flag: "no_consensus", sources_used: 0 },
    model: { final_rank: 3, confidence: 40, confidence_band: "LOW" },
  }),
  basePlayer({
    player_id: "rookie-wonder",
    name: "Rookie Wonder",
    team: "SAS",
    positions: ["PG", "G"],
    age: null,
    projection: { games: 65, minutes: 25 },
    fantasy: { per_game_value: 8.0, playoff_value: 0.5 },
    availability: { injury_risk_label: "low" },
    role: { role_change_score: 0.02 },
    schedule: { playoff_schedule_score: 0.7 },
    consensus: { consensus_rank: 45, rank_difference: 20, flag: "model_loves", sources_used: 2 },
    model: { final_rank: 4, confidence: 55, confidence_band: "MEDIUM" },
  }),
  basePlayer({
    player_id: "bench-guard",
    name: "Bench Guard",
    team: "LAL",
    positions: ["SG", "G"],
    age: 34,
    projection: { games: 40, minutes: 15 },
    fantasy: { per_game_value: 2.0, playoff_value: 0.1 },
    availability: { injury_risk_label: "moderate" },
    schedule: { playoff_schedule_score: 0.2 },
    consensus: { consensus_rank: 150, rank_difference: 1, flag: "none", sources_used: 3 },
    model: { final_rank: 5, confidence: 30, confidence_band: "LOW" },
  }),
  basePlayer({
    player_id: "two-way-big",
    name: "Two-Way Big",
    team: "BOS",
    positions: ["PF", "C", "F", "UTIL"],
    age: 27,
    projection: { games: 55, minutes: 22 },
    fantasy: { per_game_value: 6.5, playoff_value: 0.6 },
    availability: { injury_risk_label: "low" },
    schedule: { playoff_schedule_score: 0.55 },
    consensus: { consensus_rank: 60, rank_difference: -2, flag: "high_uncertainty", sources_used: 3 },
    model: { final_rank: 6, confidence: 70, confidence_band: "HIGH" },
  }),
  basePlayer({
    // fantasy.playoff_value is null exactly when the pipeline's playoff
    // schedule isn't available yet (mirrors Schedule's null fields) -- this
    // fixture is the "no schedule data" case the Playoff column must render
    // as an em-dash and sort to the end without crashing.
    player_id: "no-playoff-data",
    name: "No Playoff Data",
    team: "GSW",
    positions: ["SF", "F", "UTIL"],
    age: 26,
    projection: { games: 62, minutes: 26 },
    fantasy: { per_game_value: 9.0, playoff_value: null },
    availability: { injury_risk_label: "low" },
    schedule: { playoff_schedule_score: null },
    consensus: { consensus_rank: 70, rank_difference: 0, flag: "none", sources_used: 3 },
    model: { final_rank: 7, confidence: 60, confidence_band: "MEDIUM" },
  }),
  basePlayer({
    // Task 17 detail-view fixture: the only player with a full analysis
    // paragraph, per-source consensus rows (including an imputed one),
    // sources, and a published (non-null) schedule with a favorable
    // (>=4), unfavorable (<=2), and neutral week all present. final_rank 8
    // keeps it sorted after every Task 16 fixture so it doesn't shift any
    // existing index-based table assertion.
    player_id: "detail-rich",
    name: "Detail Rich",
    team: "PHX",
    positions: ["SG", "SF", "G"],
    age: 28,
    projection: { games: 68, minutes: 31 },
    fantasy: {
      per_game_value: 12.4,
      playoff_value: 1.1,
      availability_adjusted_value: 11.8,
      regular_season_value: 12.0,
      combined_value: 12.2,
      final_score: 85.3,
      per_game_zscores: { fg_pct: 0.4, ft_pct: -0.2, tpm: 1.1, pts: 1.8, reb: -0.5, ast: 0.9, stl: 0.3, blk: -0.8, tov: -0.4 },
    },
    availability: {
      injury_risk_label: "moderate",
      injury_risk_score: 0.35,
      raw_projected_games: 74,
      injury_adjusted_games: 68,
    },
    role: {
      role_change_score: 0.08,
      direction: "positive",
      minutes_delta: 2.5,
      usage_delta: 0.03,
      team_changed: true,
      pace_multiplier: 1.05,
    },
    schedule: {
      week_games: { "19": 4, "20": 2, "21": 3 },
      playoff_games: 9,
      playoff_b2bs: 1,
      playoff_schedule_score: 0.6,
      expected_playoff_games: 8.5,
      // small windows map (applyWindow test fixture): "19-21" mirrors the
      // top-level fields above exactly (the pipeline's default-window
      // identity guarantee); "18-20" is deliberately different so a window
      // switch is a visible, hand-verifiable change
      windows: {
        "19-21": {
          week_games: { "19": 4, "20": 2, "21": 3 },
          playoff_games: 9,
          playoff_b2bs: 1,
          playoff_schedule_score: 0.6,
          expected_playoff_games: 8.5,
          playoff_value_z: 1.1,
        },
        "18-20": {
          week_games: { "18": 2, "19": 4, "20": 2 },
          playoff_games: 8,
          playoff_b2bs: 0,
          playoff_schedule_score: 0.5,
          expected_playoff_games: 7.0,
          playoff_value_z: 0.4,
        },
      },
    },
    consensus: {
      consensus_rank: 22,
      rank_difference: -14,
      flag: "high_uncertainty",
      sources_used: 2,
      per_source: {
        "ESPN": { rank: 18, imputed: false },
        "Rotowire": { rank: 26, imputed: true },
      },
    },
    model: { final_rank: 8, model_rank: 20, confidence: 62, confidence_band: "MEDIUM" },
    analysis: {
      explanation: "Detail Rich profiles as a high-usage combo guard whose per-game efficiency clears most of the field, but a moderate injury flag and a mid-season team change keep the composite score a notch below the projection alone.",
      strengths: ["Elite 3PM volume", "Playoff schedule tilt"],
      risks: ["Moderate injury risk", "New role after trade"],
    },
    sources: [
      { source: "ESPN", url: "https://espn.com/nba/player/1", retrieved: "2026-08-01", type: "expert_rank" },
      { source: "Rotowire", url: "https://rotowire.com/nba/player/1", retrieved: "2026-08-02", type: "projection" },
    ],
  }),
  basePlayer({
    // Playoff Sched grade-column fixture: a perfectly even 4/4/4 window
    // grades A+ (12) -- the one non-null, high-signal case the RankingsTable
    // and PlayerDetail grade tests pin against. final_rank 9 keeps it sorted
    // after every other fixture so it doesn't shift any index-based assertion.
    player_id: "playoff-grade-a",
    name: "Playoff Grade A",
    team: "OKC",
    positions: ["PG", "G"],
    age: 24,
    projection: { games: 48, minutes: 29 },
    fantasy: { per_game_value: 7.0, playoff_value: 0.9 },
    availability: { injury_risk_label: "low" },
    schedule: { week_games: { "19": 4, "20": 4, "21": 4 }, playoff_games: 12, playoff_b2bs: 0 },
    consensus: { consensus_rank: 35, rank_difference: 3, flag: "none", sources_used: 3 },
    model: { final_rank: 9, confidence: 58, confidence_band: "MEDIUM" },
  }),
];
