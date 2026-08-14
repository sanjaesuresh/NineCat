import { useEffect, useMemo, useState } from "react";
import { Filters } from "./components/Filters";
import { PlayerDetail } from "./components/PlayerDetail";
import { RankingsTable } from "./components/RankingsTable";
import { defaultFilters, filterPlayers, type FilterState } from "./components/filterPlayers";
import { DataUnavailableError, loadPlayers } from "./lib/data";
import { applyWindow, componentContributions, extractDefaultWeights, recomputeScores, weightsEqual } from "./lib/recompute";
import type { CompositeWeights, Dataset, Player } from "./lib/types";
import { Movers } from "./pages/Movers";
import { Settings } from "./pages/Settings";

type LoadState =
  | { status: "loading" }
  | { status: "unavailable"; message: string }
  | { status: "ready"; dataset: Dataset };

type Tab = "rankings" | "movers" | "settings";

const TABS: { id: Tab; label: string }[] = [
  { id: "rankings", label: "Rankings" },
  { id: "movers", label: "Movers" },
  { id: "settings", label: "Settings" },
];

// mirrors Settings.tsx's own debounce -- recomputeScores (O(n log n) over 200
// players) should run once per pause in slider dragging, not once per event
const RECOMPUTE_DEBOUNCE_MS = 150;

// date-only strings ("2026-08-14") are formatted in UTC so negative-offset
// timezones don't shift the projection date back a day
function formatDate(isoDate: string): string {
  const parsed = new Date(isoDate);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

// full timestamps render in the viewer's local time; raw value stays in the
// title attribute for precision
function formatTimestamp(isoTimestamp: string): string {
  const parsed = new Date(isoTimestamp);
  if (Number.isNaN(parsed.getTime())) return isoTimestamp;
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Primary rankings page: filter bar + sortable table (Task 16) over the
 * loaded dataset, with a row-selection side panel showing the full player
 * detail view + charts (Task 17). */
function App() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [filters, setFilters] = useState<FilterState>(defaultFilters);
  // shared across tabs so selecting a player on Movers (or Rankings) keeps
  // its detail panel state if the user switches tabs and back; stored as an
  // id (not the Player object) so the open detail panel always re-derives
  // from the currently windowed/re-ranked player list instead of going stale
  // when the window or weights change
  const [selectedPlayerId, setSelectedPlayerId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("rankings");
  // null = "still the shipped default" -- avoids needing the dataset loaded
  // just to seed these with a real value
  const [selectedWindow, setSelectedWindow] = useState<string | null>(null);
  const [weights, setWeights] = useState<CompositeWeights | null>(null);
  const [debouncedWeights, setDebouncedWeights] = useState<CompositeWeights | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedWeights(weights), RECOMPUTE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [weights]);

  useEffect(() => {
    let cancelled = false;
    loadPlayers()
      .then((dataset) => {
        if (!cancelled) setState({ status: "ready", dataset });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof DataUnavailableError
            ? err.message
            : "Something went wrong loading the dataset.";
        setState({ status: "unavailable", message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Team options and filtered rows only need recomputing when the dataset or
  // filters actually change -- both can be expensive over 200+ players.
  const teams = useMemo(() => {
    if (state.status !== "ready") return [];
    return [...new Set(state.dataset.players.map((p) => p.team))].sort();
  }, [state]);

  const defaultWeights = useMemo(
    () => (state.status === "ready" ? extractDefaultWeights(state.dataset) : null),
    [state],
  );
  const activeWeights = weights ?? defaultWeights;
  // falls back instantly to the default rather than waiting out the debounce
  // timer on first render (weights/debouncedWeights both start null)
  const activeDebouncedWeights = debouncedWeights ?? defaultWeights;
  const activeWindow = selectedWindow ?? (state.status === "ready" ? state.dataset.default_window : null);

  const isDefaultWindow = state.status === "ready" && activeWindow === state.dataset.default_window;
  const isDefaultWeights =
    activeDebouncedWeights !== null && defaultWeights !== null && weightsEqual(activeDebouncedWeights, defaultWeights);

  // single source of truth for "what the Rankings table, Movers, and the
  // detail panel show": the shipped order/values, byte-for-byte, UNLESS the
  // user has picked a non-default window and/or non-default weights -- then
  // every player is re-ranked under applyWindow + recomputeScores together
  // (the same mechanism Settings' own preview uses), composing both choices
  // into one list instead of two independent transforms
  const basePlayers = useMemo((): Player[] => {
    if (state.status !== "ready") return [];
    if (isDefaultWindow && isDefaultWeights) return state.dataset.players;

    const effectiveWeights = activeDebouncedWeights ?? extractDefaultWeights(state.dataset);
    const windowed = applyWindow(state.dataset.players, activeWindow ?? state.dataset.default_window);
    const ranked = recomputeScores(windowed, effectiveWeights);
    return ranked.map((r) => ({
      ...r.player,
      model: {
        ...r.player.model,
        final_rank: r.newRank,
        component_contributions: componentContributions(r.player, effectiveWeights),
      },
    }));
  }, [state, activeWindow, activeDebouncedWeights, isDefaultWindow, isDefaultWeights]);

  const filteredPlayers = useMemo(() => filterPlayers(basePlayers, filters), [basePlayers, filters]);

  const selectedPlayer = useMemo(
    () => basePlayers.find((p) => p.player_id === selectedPlayerId) ?? null,
    [basePlayers, selectedPlayerId],
  );

  if (state.status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-400">
        Loading projections...
      </div>
    );
  }

  if (state.status === "unavailable") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-2 bg-slate-950 px-4 text-center">
        <p className="text-lg font-medium text-slate-100">No dataset found</p>
        <p className="max-w-md text-sm text-slate-400">{state.message}</p>
        <p className="mt-2 text-sm text-slate-500">
          Run the projections pipeline, then{" "}
          <code className="rounded bg-slate-800 px-1 text-slate-300">npm run sync-data</code>.
        </p>
      </div>
    );
  }

  const { dataset } = state;
  // non-null once state.status === "ready" (activeWindow's other branch only
  // applies while still loading) -- narrowed here for the JSX below
  const currentWindow = activeWindow ?? dataset.default_window;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4">
        <h1 className="text-xl font-semibold text-slate-100">Season {dataset.season}</h1>
        <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-400">
          <div>
            <dt className="inline font-medium text-slate-300">Projection date:</dt>{" "}
            <dd className="inline">{formatDate(dataset.projection_date)}</dd>
          </div>
          <div>
            <dt className="inline font-medium text-slate-300">Last updated:</dt>{" "}
            <dd className="inline" title={dataset.last_updated}>
              {formatTimestamp(dataset.last_updated)}
            </dd>
          </div>
          <div>
            <dt className="inline font-medium text-slate-300">Players:</dt>{" "}
            <dd className="inline">{dataset.players.length}</dd>
          </div>
          <div className="flex items-center gap-1.5">
            <label htmlFor="playoff-window-select" className="font-medium text-slate-300">
              Playoff weeks
            </label>
            <select
              id="playoff-window-select"
              value={currentWindow}
              onChange={(e) => setSelectedWindow(e.target.value)}
              className="min-h-[24px] rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-sm text-slate-100 focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400"
            >
              {dataset.candidate_windows.map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>
          </div>
        </dl>
        {currentWindow !== dataset.default_window && (
          <p className="mt-1 text-sm text-slate-500">ranking recomputed for weeks {currentWindow}</p>
        )}
        {!dataset.schedule_available && (
          <p className="mt-2 rounded bg-amber-950 px-3 py-1.5 text-sm text-amber-200">
            {dataset.playoff_window_force_unavailable
              ? // schedule fetched fine, but its playoff window (weeks 19-21) has
                // zero games league-wide -- a partial/early-release NBA schedule,
                // not the same as no schedule having fetched at all
                "Partial schedule published — playoff window not yet available -- playoff-dependent fields are null until it is."
              : "Playoff schedule data isn't available yet -- playoff-dependent fields are null until it is."}
          </p>
        )}
      </header>

      {/* plain buttons + aria-current, not the ARIA tabs pattern -- native
       * buttons are keyboard-operable (Tab, Enter/Space) without needing
       * roving tabindex/arrow-key wiring for what's really page navigation */}
      <nav aria-label="Dashboard sections" className="border-b border-slate-800 px-6">
        <div className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              aria-current={activeTab === tab.id ? "page" : undefined}
              onClick={() => setActiveTab(tab.id)}
              className={`min-h-[24px] rounded-t border-b-2 px-3 py-2 text-sm font-medium outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-amber-400 ${
                activeTab === tab.id
                  ? "border-amber-400 text-amber-300"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </nav>

      <main className="flex flex-col gap-4 px-6 py-4">
        {activeTab === "rankings" && (
          <>
            <Filters
              filters={filters}
              onChange={setFilters}
              teams={teams}
              resultCount={filteredPlayers.length}
              totalCount={basePlayers.length}
            />

            {/* below lg, stack the detail panel under the table instead of beside
             * it -- a fixed-width w-80 aside next to a flex-1 table with no wrap
             * guarantees page-level horizontal overflow on narrow viewports */}
            <div className="flex flex-col items-start gap-4 lg:flex-row">
              <div className="min-w-0 w-full flex-1">
                {filteredPlayers.length === 0 ? (
                  <div className="flex flex-col items-center gap-3 rounded-lg border border-slate-800 bg-slate-900 px-6 py-12 text-center">
                    <p className="text-slate-300">No players match the current filters.</p>
                    <button
                      type="button"
                      onClick={() => setFilters(defaultFilters)}
                      className="min-h-[24px] rounded border border-slate-700 px-3 py-1.5 text-sm font-medium text-slate-300 hover:border-amber-400 hover:text-amber-300 focus:outline-none focus-visible:ring-1 focus-visible:ring-amber-400"
                    >
                      Clear filters
                    </button>
                  </div>
                ) : (
                  <RankingsTable
                    players={filteredPlayers}
                    selectedPlayerId={selectedPlayer?.player_id ?? null}
                    onSelectPlayer={(player) => setSelectedPlayerId(player.player_id)}
                  />
                )}
              </div>

              {selectedPlayer && (
                // key by player_id so switching the selected row remounts the
                // panel cleanly (fresh focus-management effect, no stale
                // <details> open state carried over from the previous player)
                <PlayerDetail
                  key={selectedPlayer.player_id}
                  player={selectedPlayer}
                  onClose={() => setSelectedPlayerId(null)}
                />
              )}
            </div>
          </>
        )}

        {activeTab === "movers" && (
          <Movers
            players={basePlayers}
            selectedPlayer={selectedPlayer}
            onSelectPlayer={(player) => setSelectedPlayerId(player.player_id)}
            onCloseDetail={() => setSelectedPlayerId(null)}
          />
        )}

        {activeTab === "settings" && (
          <Settings
            dataset={dataset}
            weights={activeWeights ?? extractDefaultWeights(dataset)}
            onWeightsChange={setWeights}
            windowKey={currentWindow}
          />
        )}
      </main>
    </div>
  );
}

export default App;
