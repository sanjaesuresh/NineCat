import { useMemo, useState, type KeyboardEvent } from "react";
import type { CategoryKey, Player } from "../lib/types";
import { DEFAULT_COLUMNS, DEFAULT_SORT, EXTRA_COLUMNS, sortPlayers, type SortState } from "./columns";

export interface RankingsTableProps {
  players: Player[];
  selectedPlayerId: string | null;
  onSelectPlayer: (player: Player) => void;
  /** Active punt-build categories -- only the per-category z columns read
   * this (to mute a punted category's cell); defaults to none. */
  punts?: CategoryKey[];
}

function SortIcon({ direction }: { direction: "asc" | "desc" | null }) {
  if (direction === null) {
    return (
      <span aria-hidden="true" className="text-slate-600">
        ↕
      </span>
    );
  }
  return (
    <span aria-hidden="true" className="text-amber-400">
      {direction === "asc" ? "↑" : "↓"}
    </span>
  );
}

/**
 * Primary rankings table: sortable real <table>, sticky header, a column
 * picker for the optional z-score/age/value columns, and keyboard-selectable
 * rows (Task 17 wires the click/Enter target to a detail panel).
 */
export function RankingsTable({ players, selectedPlayerId, onSelectPlayer, punts = [] }: RankingsTableProps) {
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const [extraColumnIds, setExtraColumnIds] = useState<string[]>([]);
  const [columnPickerOpen, setColumnPickerOpen] = useState(false);

  const columns = useMemo(() => {
    const extra = EXTRA_COLUMNS.filter((c) => extraColumnIds.includes(c.id));
    return [...DEFAULT_COLUMNS, ...extra];
  }, [extraColumnIds]);

  const sortedPlayers = useMemo(() => sortPlayers(players, columns, sort), [players, columns, sort]);

  const toggleSort = (columnId: string) => {
    setSort((prev) => {
      if (prev.columnId !== columnId) return { columnId, direction: "asc" };
      return { columnId, direction: prev.direction === "asc" ? "desc" : "asc" };
    });
  };

  const toggleExtraColumn = (columnId: string) => {
    setExtraColumnIds((prev) =>
      prev.includes(columnId) ? prev.filter((id) => id !== columnId) : [...prev, columnId],
    );
  };

  const handleRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, player: Player) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelectPlayer(player);
    }
  };

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <span className="text-sm text-slate-400">{sortedPlayers.length} players shown</span>
        <details
          className="relative"
          open={columnPickerOpen}
          onToggle={(e) => setColumnPickerOpen(e.currentTarget.open)}
        >
          {/* native <details>/<summary> is keyboard-operable (Tab, Enter/Space)
           * out of the box; role="button" + aria-expanded make the exposed
           * accessible role explicit since some UA/AT combinations don't
           * apply HTML-AAM's implicit summary->button mapping consistently */}
          <summary
            role="button"
            aria-expanded={columnPickerOpen}
            className="min-h-[24px] cursor-pointer list-none rounded border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 hover:border-amber-400 hover:text-amber-300 focus:outline-none focus-visible:ring-1 focus-visible:ring-amber-400"
          >
            Columns
          </summary>
          <div className="absolute right-0 z-20 mt-2 w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 shadow-lg">
            <p className="px-1 pb-1 text-xs font-medium text-slate-500">Add columns</p>
            <div className="flex max-h-64 flex-col gap-0.5 overflow-y-auto">
              {EXTRA_COLUMNS.map((col) => (
                <label
                  key={col.id}
                  className="flex min-h-[24px] items-center gap-2 rounded px-1 py-1 text-sm text-slate-300 hover:bg-slate-800"
                >
                  <input
                    type="checkbox"
                    checked={extraColumnIds.includes(col.id)}
                    onChange={() => toggleExtraColumn(col.id)}
                    className="h-4 w-4 accent-amber-400"
                  />
                  {col.header}
                </label>
              ))}
            </div>
          </div>
        </details>
      </div>

      <div className="relative overflow-x-auto">
        <table className="w-full min-w-[960px] border-collapse text-sm">
          <caption className="sr-only">
            Player rankings, sortable by column. Activate a column header button to sort; select a row to
            view player detail.
          </caption>
          <thead className="sticky top-0 z-10 bg-slate-950">
            <tr>
              {columns.map((col) => {
                const isSorted = sort.columnId === col.id;
                const ariaSort = col.numeric
                  ? isSorted
                    ? sort.direction === "asc"
                      ? "ascending"
                      : "descending"
                    : "none"
                  : undefined;
                return (
                  <th
                    key={col.id}
                    scope="col"
                    aria-sort={ariaSort}
                    className={`whitespace-nowrap px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400 ${
                      col.align === "right" ? "text-right" : "text-left"
                    }`}
                  >
                    {col.numeric ? (
                      <button
                        type="button"
                        onClick={() => toggleSort(col.id)}
                        className={`inline-flex min-h-[24px] items-center gap-1 rounded focus:outline-none focus-visible:ring-1 focus-visible:ring-amber-400 ${
                          col.align === "right" ? "flex-row-reverse" : ""
                        }`}
                      >
                        {col.header}
                        <SortIcon direction={isSorted ? sort.direction : null} />
                        <span className="sr-only">
                          , sort by {col.header} {isSorted && sort.direction === "asc" ? "descending" : "ascending"}
                        </span>
                      </button>
                    ) : (
                      col.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sortedPlayers.map((player, index) => {
              const isSelected = player.player_id === selectedPlayerId;
              return (
                <tr
                  key={player.player_id}
                  tabIndex={0}
                  aria-selected={isSelected}
                  onClick={() => onSelectPlayer(player)}
                  onKeyDown={(e) => handleRowKeyDown(e, player)}
                  className={`cursor-pointer border-t border-slate-800/60 outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-amber-400 ${
                    isSelected
                      ? "bg-amber-400/10"
                      : index % 2 === 0
                        ? "bg-slate-900"
                        : "bg-slate-900/40"
                  } hover:bg-slate-800/60`}
                >
                  {columns.map((col) => (
                    <td
                      key={col.id}
                      className={`whitespace-nowrap px-3 py-2.5 tabular-nums text-slate-200 ${
                        col.align === "right" ? "text-right" : "text-left"
                      }`}
                    >
                      {col.render(player, punts)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
