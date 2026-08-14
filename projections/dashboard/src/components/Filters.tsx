import type { InjuryRiskLabel } from "../lib/types";
import {
  CONSENSUS_FLAG_OPTIONS,
  POSITION_OPTIONS,
  defaultFilters,
  type ConsensusFlagFilter,
  type FilterState,
  type RoleDirectionFilter,
} from "./filterPlayers";

const INJURY_OPTIONS: { value: InjuryRiskLabel; label: string }[] = [
  { value: "low", label: "Low" },
  { value: "moderate", label: "Moderate" },
  { value: "high", label: "High" },
];

const ROLE_DIRECTION_OPTIONS: { value: RoleDirectionFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "positive", label: "Positive" },
  { value: "negative", label: "Negative" },
  { value: "neutral", label: "Neutral" },
];

// shared control chrome so every field lines up on the same baseline
const labelClass = "text-xs font-medium text-slate-400";
const inputClass =
  "min-h-[24px] rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-slate-100 " +
  "placeholder:text-slate-500 focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400";

export interface FiltersProps {
  filters: FilterState;
  onChange: (next: FilterState) => void;
  teams: string[];
  resultCount: number;
  totalCount: number;
}

/** Controlled filter bar for the rankings table. Every control writes a full
 * next FilterState back through onChange -- filtering itself happens in
 * filterPlayers.ts so this component stays a thin, testable view. */
export function Filters({ filters, onChange, teams, resultCount, totalCount }: FiltersProps) {
  const set = <K extends keyof FilterState>(key: K, value: FilterState[K]) => {
    onChange({ ...filters, [key]: value });
  };

  const parseNumberOrNull = (raw: string): number | null => (raw === "" ? null : Number(raw));

  const toggleInjury = (label: InjuryRiskLabel) => {
    const next = filters.injuryRisk.includes(label)
      ? filters.injuryRisk.filter((l) => l !== label)
      : [...filters.injuryRisk, label];
    set("injuryRisk", next);
  };

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <div className="flex min-w-[12rem] flex-col gap-1">
          <label htmlFor="filter-search" className={labelClass}>
            Search
          </label>
          <input
            id="filter-search"
            type="text"
            value={filters.search}
            onChange={(e) => set("search", e.target.value)}
            placeholder="Player name"
            className={inputClass}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="filter-team" className={labelClass}>
            Team
          </label>
          <select
            id="filter-team"
            value={filters.team}
            onChange={(e) => set("team", e.target.value)}
            className={inputClass}
          >
            <option value="">All teams</option>
            {teams.map((team) => (
              <option key={team} value={team}>
                {team}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="filter-position" className={labelClass}>
            Position
          </label>
          <select
            id="filter-position"
            value={filters.position}
            onChange={(e) => set("position", e.target.value)}
            className={inputClass}
          >
            <option value="">All positions</option>
            {POSITION_OPTIONS.map((pos) => (
              <option key={pos} value={pos}>
                {pos}
              </option>
            ))}
          </select>
        </div>

        <fieldset className="flex flex-col gap-1">
          <legend className={labelClass}>Injury risk</legend>
          <div className="flex gap-2">
            {INJURY_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className="flex min-h-[24px] items-center gap-1 text-sm text-slate-300"
              >
                <input
                  type="checkbox"
                  checked={filters.injuryRisk.includes(opt.value)}
                  onChange={() => toggleInjury(opt.value)}
                  className="h-4 w-4 accent-amber-400"
                />
                {opt.label}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="flex flex-col gap-1">
          <label htmlFor="filter-min-gp" className={labelClass}>
            Min GP
          </label>
          <input
            id="filter-min-gp"
            type="number"
            inputMode="numeric"
            min={0}
            value={filters.minGp ?? ""}
            onChange={(e) => set("minGp", parseNumberOrNull(e.target.value))}
            className={`${inputClass} w-20`}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="filter-min-9cat" className={labelClass}>
            Min 9CAT
          </label>
          <input
            id="filter-min-9cat"
            type="number"
            inputMode="decimal"
            step="0.1"
            value={filters.min9cat ?? ""}
            onChange={(e) => set("min9cat", parseNumberOrNull(e.target.value))}
            className={`${inputClass} w-20`}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="filter-min-age" className={labelClass}>
            Min age
          </label>
          <input
            id="filter-min-age"
            type="number"
            inputMode="numeric"
            min={0}
            value={filters.minAge ?? ""}
            onChange={(e) => set("minAge", parseNumberOrNull(e.target.value))}
            className={`${inputClass} w-20`}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="filter-max-age" className={labelClass}>
            Max age
          </label>
          <input
            id="filter-max-age"
            type="number"
            inputMode="numeric"
            min={0}
            value={filters.maxAge ?? ""}
            onChange={(e) => set("maxAge", parseNumberOrNull(e.target.value))}
            className={`${inputClass} w-20`}
          />
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="filter-role-direction" className={labelClass}>
            Role change
          </label>
          <select
            id="filter-role-direction"
            value={filters.roleDirection}
            onChange={(e) => set("roleDirection", e.target.value as RoleDirectionFilter)}
            className={inputClass}
          >
            {ROLE_DIRECTION_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="filter-consensus-flag" className={labelClass}>
            Consensus flag
          </label>
          <select
            id="filter-consensus-flag"
            value={filters.consensusFlag}
            onChange={(e) => set("consensusFlag", e.target.value as ConsensusFlagFilter)}
            className={inputClass}
          >
            {CONSENSUS_FLAG_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <label className="flex min-h-[24px] items-center gap-1.5 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={filters.rookieOnly}
            onChange={(e) => set("rookieOnly", e.target.checked)}
            className="h-4 w-4 accent-amber-400"
          />
          Rookies only
        </label>

        <label className="flex min-h-[24px] items-center gap-1.5 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={filters.teamChangedOnly}
            onChange={(e) => set("teamChangedOnly", e.target.checked)}
            className="h-4 w-4 accent-amber-400"
          />
          Team changed
        </label>

        <button
          type="button"
          onClick={() => onChange(defaultFilters)}
          className="min-h-[24px] rounded border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 hover:border-amber-400 hover:text-amber-300 focus:outline-none focus:ring-1 focus:ring-amber-400"
        >
          Clear all
        </button>
      </div>

      <p aria-live="polite" className="mt-3 text-sm text-slate-400">
        {resultCount} of {totalCount} players
      </p>
    </div>
  );
}
