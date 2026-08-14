import { useMemo } from "react";
import { DisagreementChart } from "../components/charts/DisagreementChart";
import { PlayerDetail } from "../components/PlayerDetail";
import type { Player } from "../lib/types";
import { computeMovers, type MoverEntry } from "./moversData";

export interface MoversProps {
  players: Player[];
  selectedPlayer: Player | null;
  onSelectPlayer: (player: Player) => void;
  onCloseDetail: () => void;
}

function MoverRow({ entry, isSelected, onSelect }: { entry: MoverEntry; isSelected: boolean; onSelect: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        // stacks name/detail vertically below sm -- at narrow widths (the
        // dashboard's 360px floor) a single row can't fit a full player
        // name next to the detail text without truncating names into
        // unreadable "John..." fragments, so drop the horizontal squeeze
        // and let the detail text wrap under the name instead
        className={`flex min-h-[24px] w-full flex-col items-start gap-1 rounded px-2 py-2 text-left outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-amber-400 sm:flex-row sm:items-center sm:justify-between sm:gap-3 ${
          isSelected ? "bg-amber-400/10" : "hover:bg-slate-800/60"
        }`}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="w-8 shrink-0 text-right tabular-nums text-slate-500">#{entry.player.model.final_rank}</span>
          <span className="min-w-0">
            <span className="block truncate font-medium text-slate-100">{entry.player.name}</span>
            <span className="text-xs text-slate-400">{entry.player.team}</span>
          </span>
        </span>
        <span className="pl-10 tabular-nums text-xs text-slate-400 sm:shrink-0 sm:whitespace-nowrap sm:pl-0">
          {entry.detail}
        </span>
      </button>
    </li>
  );
}

function EmptySection({ message }: { message: string }) {
  return <p className="px-2 py-3 text-sm text-slate-500">{message}</p>;
}

function MoverSection({
  title,
  description,
  entries,
  emptyMessage,
  selectedPlayerId,
  onSelectPlayer,
}: {
  title: string;
  description: string;
  entries: MoverEntry[];
  emptyMessage: string;
  selectedPlayerId: string | null;
  onSelectPlayer: (player: Player) => void;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900">
      <div className="border-b border-slate-800 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
        <p className="mt-0.5 text-xs text-slate-500">{description}</p>
      </div>
      {entries.length === 0 ? (
        <EmptySection message={emptyMessage} />
      ) : (
        <ul className="flex flex-col gap-0.5 p-2">
          {entries.map((entry) => (
            <MoverRow
              key={entry.player.player_id}
              entry={entry}
              isSelected={entry.player.player_id === selectedPlayerId}
              onSelect={() => onSelectPlayer(entry.player)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Movers page (Task 18): five pipeline-wide "what moved and why" sections
 * computed by the pure helpers in moversData.ts, each entry opening the same
 * PlayerDetail panel Rankings uses (selection state is lifted to App so it
 * carries across tabs). Unlike Rankings, this reads the full dataset, not
 * the filtered subset -- movers are a whole-pool view.
 */
export function Movers({ players, selectedPlayer, onSelectPlayer, onCloseDetail }: MoversProps) {
  const movers = useMemo(() => computeMovers(players), [players]);
  const selectedPlayerId = selectedPlayer?.player_id ?? null;

  return (
    <div className="flex flex-col items-start gap-4 lg:flex-row">
      <div className="flex min-w-0 w-full flex-1 flex-col gap-4">
        <DisagreementChart players={players} />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <MoverSection
            title="Model Risers"
            description="The model ranks these players well above consensus."
            entries={movers.risers}
            emptyMessage="No players clear the +15 rank-difference threshold this cycle."
            selectedPlayerId={selectedPlayerId}
            onSelectPlayer={onSelectPlayer}
          />
          <MoverSection
            title="Model Fallers"
            description="The model ranks these players well below consensus."
            entries={movers.fallers}
            emptyMessage="No players clear the −15 rank-difference threshold this cycle."
            selectedPlayerId={selectedPlayerId}
            onSelectPlayer={onSelectPlayer}
          />
          <MoverSection
            title="Injury Discounts"
            description="Biggest fall from per-game rank once games missed are priced in."
            entries={movers.injuryDiscounts}
            emptyMessage="No players drop 5+ spots between per-game and availability-adjusted rank."
            selectedPlayerId={selectedPlayerId}
            onSelectPlayer={onSelectPlayer}
          />
          <section className="rounded-lg border border-slate-800 bg-slate-900">
            <div className="border-b border-slate-800 px-4 py-2.5">
              <h2 className="text-sm font-semibold text-slate-100">Playoff Boosts</h2>
              <p className="mt-0.5 text-xs text-slate-500">Highest playoff-schedule contribution to composite score.</p>
            </div>
            {!movers.playoffDataAvailable ? (
              <div className="mx-2 my-2 rounded bg-amber-950 px-3 py-2 text-sm text-amber-200">
                2026-27 playoff schedule not yet published -- playoff-schedule contributions are null until it is.
              </div>
            ) : movers.playoffBoosts.length === 0 ? (
              <EmptySection message="No players clear the playoff-schedule boost threshold this cycle." />
            ) : (
              <ul className="flex flex-col gap-0.5 p-2">
                {movers.playoffBoosts.map((entry) => (
                  <MoverRow
                    key={entry.player.player_id}
                    entry={entry}
                    isSelected={entry.player.player_id === selectedPlayerId}
                    onSelect={() => onSelectPlayer(entry.player)}
                  />
                ))}
              </ul>
            )}
          </section>
          <MoverSection
            title="Breakouts"
            description="Largest positive role-change signal -- more minutes/usage than last season's line."
            entries={movers.breakouts}
            emptyMessage="No players clear the role-change-score threshold this cycle."
            selectedPlayerId={selectedPlayerId}
            onSelectPlayer={onSelectPlayer}
          />
        </div>
      </div>

      {selectedPlayer && (
        <PlayerDetail key={selectedPlayer.player_id} player={selectedPlayer} onClose={onCloseDetail} />
      )}
    </div>
  );
}
