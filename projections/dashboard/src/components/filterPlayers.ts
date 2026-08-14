import type { DisagreementFlag, InjuryRiskLabel, Player } from "../lib/types";

export type RoleDirectionFilter = "all" | "positive" | "negative" | "neutral";
export type ConsensusFlagFilter = DisagreementFlag | "all";

export interface FilterState {
  search: string;
  team: string; // "" = all teams
  position: string; // "" = all positions, else one of POSITION_OPTIONS
  injuryRisk: InjuryRiskLabel[]; // multi-select; empty = all
  minGp: number | null;
  min9cat: number | null;
  minAge: number | null;
  maxAge: number | null;
  rookieOnly: boolean;
  teamChangedOnly: boolean;
  roleDirection: RoleDirectionFilter;
  consensusFlag: ConsensusFlagFilter;
}

export const POSITION_OPTIONS = ["PG", "SG", "G", "SF", "PF", "F", "C", "UTIL"] as const;

export const CONSENSUS_FLAG_OPTIONS: { value: ConsensusFlagFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "model_loves", label: "Model loves" },
  { value: "model_fades", label: "Model fades" },
  { value: "high_uncertainty", label: "High uncertainty" },
  { value: "no_consensus", label: "No consensus" },
  { value: "none", label: "No flag" },
];

export const defaultFilters: FilterState = {
  search: "",
  team: "",
  position: "",
  injuryRisk: [],
  minGp: null,
  min9cat: null,
  minAge: null,
  maxAge: null,
  rookieOnly: false,
  teamChangedOnly: false,
  roleDirection: "all",
  consensusFlag: "all",
};

/** Strips combining diacritical marks after NFD-decomposing, so "jokic"
 * matches "Jokić" -- the accent is a separate combining codepoint in NFD. */
export function normalizeSearchText(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

/** Rookies aren't in any historical NBA data source; the pipeline marks them
 * with a synthetic "rookie-" id prefix instead of an NBA player_id. */
export function isRookie(player: Player): boolean {
  return player.player_id.startsWith("rookie-");
}

export function filterPlayers(players: Player[], filters: FilterState): Player[] {
  const query = normalizeSearchText(filters.search);

  return players.filter((player) => {
    if (query && !normalizeSearchText(player.name).includes(query)) return false;
    if (filters.team && player.team !== filters.team) return false;
    if (filters.position && !player.positions.includes(filters.position)) return false;
    if (
      filters.injuryRisk.length > 0 &&
      !filters.injuryRisk.includes(player.availability.injury_risk_label)
    ) {
      return false;
    }
    if (filters.minGp !== null && player.projection.games < filters.minGp) return false;
    if (filters.min9cat !== null && player.fantasy.per_game_value < filters.min9cat) return false;
    // null age can't satisfy an explicit bound -- excluded rather than guessed
    if (filters.minAge !== null && (player.age === null || player.age < filters.minAge)) return false;
    if (filters.maxAge !== null && (player.age === null || player.age > filters.maxAge)) return false;
    if (filters.rookieOnly && !isRookie(player)) return false;
    if (filters.teamChangedOnly && !player.role.team_changed) return false;
    if (filters.roleDirection !== "all" && player.role.direction !== filters.roleDirection) return false;
    if (filters.consensusFlag !== "all" && player.consensus.flag !== filters.consensusFlag) return false;
    return true;
  });
}
