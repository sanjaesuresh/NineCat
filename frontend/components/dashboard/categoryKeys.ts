import { CATEGORIES } from "@/components/categories";

/**
 * Three different key systems name the same 9 categories across the backend
 * contract, and mixing them up silently returns undefined (rendered as an
 * innocuous-looking em-dash) rather than an error, so these maps are the one
 * place that translation happens:
 *  - display label (CATEGORIES, e.g. "FG%") — what the UI shows
 *  - contract key (e.g. "fg_pct") — how `averages` and `build_profile` key their dicts
 *  - Yahoo stat id (e.g. "5") — how `matchup.category_totals` keys its dict (JSON string)
 */
export const CONTRACT_KEY_BY_LABEL: Record<(typeof CATEGORIES)[number], string> = {
  PTS: "pts",
  REB: "reb",
  AST: "ast",
  STL: "stl",
  BLK: "blk",
  "3PM": "tpm",
  "FG%": "fg_pct",
  "FT%": "ft_pct",
  TO: "tov",
};

// Yahoo's fixed NBA fantasy stat-id scheme for these 9 categories
export const LABEL_BY_STAT_ID: Record<string, (typeof CATEGORIES)[number]> = {
  "5": "FG%",
  "8": "FT%",
  "10": "3PM",
  "12": "PTS",
  "15": "REB",
  "16": "AST",
  "17": "STL",
  "18": "BLK",
  "19": "TO",
};

// derived from LABEL_BY_STAT_ID so the stat-id scheme stays the single source of truth
export const STAT_ID_BY_LABEL: Record<(typeof CATEGORIES)[number], string> = Object.fromEntries(
  Object.entries(LABEL_BY_STAT_ID).map(([id, label]) => [label, id]),
) as Record<(typeof CATEGORIES)[number], string>;
