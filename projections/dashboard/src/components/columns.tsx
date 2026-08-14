import type { ReactNode } from "react";
import type { CategoryKey, Player } from "../lib/types";
import { formatGrade, gradePlayoffSchedule, playoffGradeSortValue, type PlayoffGrade } from "../lib/playoffGrade";
import { ConfidenceChip, InjuryChip, RankDeltaMarker } from "./badges";

export interface ColumnDef {
  id: string;
  header: string;
  /** Numeric columns get a sort button in the header; non-numeric columns
   * (Player, Team, Pos, Injury) render as plain <th> text. */
  numeric: boolean;
  align: "left" | "right";
  render: (player: Player) => ReactNode;
  /** Present only for numeric columns. Returns null for "no value" so
   * sortPlayers can push unknowns to the end instead of treating them as 0. */
  sortValue?: (player: Player) => number | null;
}

const CATEGORY_LABELS: Record<CategoryKey, string> = {
  fg_pct: "FG%",
  ft_pct: "FT%",
  tpm: "3PM",
  pts: "PTS",
  reb: "REB",
  ast: "AST",
  stl: "STL",
  blk: "BLK",
  tov: "TOV",
};

const CATEGORY_ORDER: CategoryKey[] = ["pts", "reb", "ast", "stl", "blk", "tpm", "fg_pct", "ft_pct", "tov"];

function formatNumber(value: number | null | undefined, digits = 2): string {
  return typeof value === "number" ? value.toFixed(digits) : "—";
}

/** Diverging tint for a z-score cell: 3 buckets keep every background/text
 * pairing within the AA-verified set (teal/rose/slate on dark slate), with
 * font-weight (not a 4th hue) carrying the "elite/weak" extremes. */
function zScoreClasses(z: number): string {
  const magnitude = Math.abs(z) >= 2 ? "font-semibold" : "font-normal";
  if (z > 0.5) return `bg-teal-900 text-teal-200 ${magnitude}`;
  if (z < -0.5) return `bg-rose-900 text-rose-200 ${magnitude}`;
  return `bg-slate-800 text-slate-300 ${magnitude}`;
}

function ZScoreCell({ value }: { value: number }) {
  return (
    <span className={`inline-flex min-w-[3rem] justify-end rounded px-1.5 py-0.5 tabular-nums ${zScoreClasses(value)}`}>
      {value.toFixed(2)}
    </span>
  );
}

/** Plain (non-chip) text tint for a playoff-schedule letter grade -- kept
 * subtle since this column sits next to the 9CAT z-score chips and a second
 * row of colored pills would compete with them. Keyed off the bare letter so
 * the +/- consistency modifier doesn't need its own bucket. Exported so
 * PlayerDetail's schedule-section badge matches the table cell exactly. */
export function gradeColorClass(letter: string): string {
  if (letter === "A") return "text-teal-400";
  if (letter === "B") return "text-emerald-400";
  if (letter === "C") return "text-amber-400";
  return "text-rose-400"; // D and F
}

function PlayoffGradeCell({ grade }: { grade: PlayoffGrade | null }) {
  if (grade === null) return <span className="text-slate-500">—</span>;
  return <span className={`font-medium tabular-nums ${gradeColorClass(grade.grade[0])}`}>{formatGrade(grade)}</span>;
}

function PlayerCell({ player }: { player: Player }) {
  return (
    <div className="flex flex-col py-0.5">
      <span className="font-medium text-slate-100">{player.name}</span>
      <span className="flex items-center gap-1.5 text-xs text-slate-400">
        <span className="rounded bg-slate-800 px-1 py-0.5 font-medium text-slate-300">{player.team}</span>
        <span>{player.positions.join(" · ")}</span>
      </span>
    </div>
  );
}

/** Rank, GP, MPG, 9CAT, Playoff Sched, Injury, Consensus, Confidence -- the
 * always-visible columns from the brief, in display order. (The raw
 * playoff_value z-score column lives in EXTRA_COLUMNS as "playoff" -- the
 * letter-grade column below replaces it as the default playoff signal since
 * a grade reads at a glance where a bare z-score doesn't.) */
export const DEFAULT_COLUMNS: ColumnDef[] = [
  {
    id: "rank",
    header: "Rank",
    numeric: true,
    align: "right",
    sortValue: (p) => p.model.final_rank,
    render: (p) => p.model.final_rank,
  },
  {
    id: "player",
    header: "Player",
    numeric: false,
    align: "left",
    render: (p) => <PlayerCell player={p} />,
  },
  {
    id: "team",
    header: "Team",
    numeric: false,
    align: "left",
    render: (p) => p.team,
  },
  {
    id: "pos",
    header: "Pos",
    numeric: false,
    align: "left",
    render: (p) => p.positions.join(", "),
  },
  {
    id: "gp",
    header: "GP",
    numeric: true,
    align: "right",
    sortValue: (p) => p.projection.games,
    render: (p) => Math.round(p.projection.games),
  },
  {
    id: "mpg",
    header: "MPG",
    numeric: true,
    align: "right",
    sortValue: (p) => p.projection.minutes,
    render: (p) => p.projection.minutes.toFixed(1),
  },
  {
    id: "ninecat",
    header: "9CAT",
    numeric: true,
    align: "right",
    sortValue: (p) => p.fantasy.per_game_value,
    render: (p) => formatNumber(p.fantasy.per_game_value),
  },
  {
    id: "playoffGrade",
    header: "Playoff Sched",
    numeric: true,
    align: "right",
    sortValue: (p) => playoffGradeSortValue(p.schedule.week_games),
    render: (p) => <PlayoffGradeCell grade={gradePlayoffSchedule(p.schedule.week_games)} />,
  },
  {
    id: "injury",
    header: "Injury",
    numeric: false,
    align: "left",
    render: (p) => <InjuryChip label={p.availability.injury_risk_label} />,
  },
  {
    id: "consensus",
    header: "Consensus",
    numeric: true,
    align: "right",
    sortValue: (p) => p.consensus.consensus_rank,
    render: (p) => (
      <span className="inline-flex items-center justify-end">
        {p.consensus.consensus_rank === null ? "—" : Math.round(p.consensus.consensus_rank)}
        <RankDeltaMarker rankDifference={p.consensus.rank_difference} />
      </span>
    ),
  },
  {
    id: "confidence",
    header: "Confidence",
    numeric: true,
    align: "right",
    sortValue: (p) => p.model.confidence,
    render: (p) => (
      <span className="inline-flex items-center justify-end gap-1.5">
        <span className="tabular-nums">{p.model.confidence}</span>
        <ConfidenceChip band={p.model.confidence_band} />
      </span>
    ),
  },
];

/** Optional columns surfaced through the column picker: the raw playoff
 * z-score (demoted from default -- abstract next to the Playoff Sched letter
 * grade, which now carries that signal by default), per-category z-scores,
 * availability-adjusted value, final composite score, and age. */
export const EXTRA_COLUMNS: ColumnDef[] = [
  {
    id: "playoff",
    header: "Playoff",
    numeric: true,
    align: "right",
    sortValue: (p) => p.fantasy.playoff_value ?? null,
    render: (p) => formatNumber(p.fantasy.playoff_value),
  },
  ...CATEGORY_ORDER.map((cat): ColumnDef => ({
    id: `z-${cat}`,
    header: `${CATEGORY_LABELS[cat]} z`,
    numeric: true,
    align: "right",
    sortValue: (p) => p.fantasy.per_game_zscores[cat],
    render: (p) => <ZScoreCell value={p.fantasy.per_game_zscores[cat]} />,
  })),
  {
    id: "availabilityAdjusted",
    header: "Avail-Adj",
    numeric: true,
    align: "right",
    sortValue: (p) => p.fantasy.availability_adjusted_value,
    render: (p) => formatNumber(p.fantasy.availability_adjusted_value),
  },
  {
    id: "finalScore",
    header: "Final Score",
    numeric: true,
    align: "right",
    sortValue: (p) => p.fantasy.final_score,
    render: (p) => formatNumber(p.fantasy.final_score),
  },
  {
    id: "age",
    header: "Age",
    numeric: true,
    align: "right",
    sortValue: (p) => p.age,
    render: (p) => p.age ?? "—",
  },
];

export interface SortState {
  columnId: string;
  direction: "asc" | "desc";
}

export const DEFAULT_SORT: SortState = { columnId: "rank", direction: "asc" };

/** Sorts by the given column's sortValue, nulls always last regardless of
 * direction (matches "Consensus"/"Playoff" em-dash cells reading as
 * "unknown," not "zero," in either sort direction). */
export function sortPlayers(players: Player[], columns: ColumnDef[], sort: SortState): Player[] {
  const column = columns.find((c) => c.id === sort.columnId);
  if (!column?.sortValue) return players;

  const sortValue = column.sortValue;
  const dirMul = sort.direction === "asc" ? 1 : -1;

  return [...players].sort((a, b) => {
    const av = sortValue(a);
    const bv = sortValue(b);
    if (av === null && bv === null) return 0;
    if (av === null) return 1;
    if (bv === null) return -1;
    if (av === bv) return 0;
    return av < bv ? -1 * dirMul : 1 * dirMul;
  });
}
