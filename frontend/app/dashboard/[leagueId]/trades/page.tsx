"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getLeagueOverview,
  getLeagueTrades,
  refreshLeague,
  isUnauthorized,
  ApiError,
  type LeagueTradesResponse,
  type StandingsEntry,
} from "@/lib/api";
import StaleBanner from "@/components/dashboard/StaleBanner";
import ErrorState from "@/components/dashboard/ErrorState";
import { formatSyncedAt } from "@/components/dashboard/format";
import { SkeletonCard, SkeletonTable } from "@/components/dashboard/Skeletons";
import SideStrengths from "@/components/dashboard/trades/SideStrengths";
import ExplanationsNotice from "@/components/dashboard/advisor/ExplanationsNotice";
import { modelRankByItemKey, reasoningByItemKey } from "@/components/dashboard/advisor/tokens";
import ModelReasoning from "@/components/dashboard/advisor/ModelReasoning";
import TradeCard from "@/components/dashboard/trades/TradeCard";
import ValueBasisNotice from "@/components/dashboard/trades/ValueBasisNotice";

type Status = "loading" | "ready" | "error";

export default function TradesPage() {
  const params = useParams<{ leagueId: string }>();
  const router = useRouter();
  const leagueId = Number(params.leagueId);

  const [status, setStatus] = useState<Status>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [opponents, setOpponents] = useState<StandingsEntry[]>([]);
  const [myTeamId, setMyTeamId] = useState<number | null>(null);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const selectedRef = useRef<number | null>(null);
  const [trades, setTrades] = useState<LeagueTradesResponse | null>(null);

  const failWith = useCallback((err: unknown, fallback: string) => {
    setErrorMessage(
      err instanceof ApiError
        ? `${fallback} (${err.status}).`
        : "Couldn't reach NineCat. Check your connection and try again.",
    );
    setStatus("error");
  }, []);

  /** Loads the league's other teams and returns the team to analyse, or null. */
  const loadTeams = useCallback(async (): Promise<number | null> => {
    if (!Number.isFinite(leagueId)) {
      setErrorMessage("This league link looks invalid.");
      setStatus("error");
      return null;
    }
    setStatus("loading");
    setErrorMessage(null);
    try {
      const overview = await getLeagueOverview(leagueId);
      const others = overview.standings.filter((team) => team.team_id !== overview.my_team_id);
      setMyTeamId(overview.my_team_id);
      setOpponents(others);
      // keep the user's current partner across a refresh when they're still in
      // the league; only fall back to the first team when they aren't. Read
      // through a ref, not state, so this stays out of the callback's deps
      // (and out of a re-render loop) while still seeing the live selection.
      const previous = selectedRef.current;
      const chosen = others.some((team) => team.team_id === previous)
        ? previous
        : (others[0]?.team_id ?? null);
      selectedRef.current = chosen;
      setSelectedTeamId(chosen);
      if (chosen === null) setStatus("ready");
      return chosen;
    } catch (err) {
      if (isUnauthorized(err)) {
        router.replace("/");
        return null;
      }
      failWith(err, "Couldn't load this league's teams");
      return null;
    }
  }, [leagueId, router, failWith]);

  const loadTrades = useCallback(
    async (teamId: number) => {
      setStatus("loading");
      setErrorMessage(null);
      try {
        setTrades(await getLeagueTrades(leagueId, teamId));
        setStatus("ready");
      } catch (err) {
        if (isUnauthorized(err)) {
          router.replace("/");
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          // this endpoint 404s by design when the caller's own team isn't
          // linked -- scoped to THIS call, since a 404 from the league lookup
          // means something else entirely
          setErrorMessage(
            "Your team isn't linked in this league yet, so there's no roster to trade from.",
          );
          setStatus("error");
          return;
        }
        failWith(err, "Couldn't load trade analysis");
      }
    },
    [leagueId, router, failWith],
  );

  // teams and trades are loaded as one explicit chain rather than by watching
  // selectedTeamId: an effect keyed on that state never re-fires when a
  // refresh re-picks the SAME partner, which left the page on skeletons with
  // no way out but a reload
  const loadAll = useCallback(async () => {
    const teamId = await loadTeams();
    if (teamId !== null) await loadTrades(teamId);
  }, [loadTeams, loadTrades]);

  useEffect(() => {
    // standard fetch-on-mount: loadAll only sets the status useState already initializes it to
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadAll();
  }, [loadAll]);

  async function handleRefresh() {
    await refreshLeague(leagueId);
    await loadAll();
  }

  function handlePartnerChange(teamId: number) {
    selectedRef.current = teamId;
    setSelectedTeamId(teamId);
    loadTrades(teamId);
  }

  return (
    <main className="mx-auto min-w-0 w-full max-w-5xl px-6 py-10 sm:px-10 sm:py-14">
      <h1 className="font-display text-3xl text-ink">Trades</h1>
      <p className="mt-2 max-w-2xl text-sm text-ink/80">
        Two-sided trades built from what each roster has spare and what it actually needs. Advisory
        only — NineCat never proposes anything to anyone but you.
      </p>

      {opponents.length > 0 && (
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <label htmlFor="trade-partner" className="font-mono text-xs uppercase tracking-wide text-ink/70">
            Trade partner
          </label>
          <select
            id="trade-partner"
            value={selectedTeamId ?? ""}
            onChange={(event) => handlePartnerChange(Number(event.target.value))}
            className="border border-rule bg-transparent px-3 py-1.5 font-body text-sm text-ink"
          >
            {opponents.map((team) => (
              <option key={team.team_id} value={team.team_id}>
                {team.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {status === "loading" && (
        <div className="mt-8 space-y-8" aria-busy="true">
          <p role="status" className="sr-only">
            Loading trade analysis…
          </p>
          <SkeletonCard lines={3} />
          <SkeletonTable rows={6} cols={6} />
        </div>
      )}

      {status === "error" && (
        <div className="mt-8">
          <ErrorState message={errorMessage ?? undefined} onRetry={loadAll} />
        </div>
      )}

      {status === "ready" && opponents.length === 0 && (
        <p className="mt-8 border border-dashed border-rule px-4 py-6 text-center text-ink/80">
          {myTeamId === null
            ? "Your team isn't linked in this league yet, so there's nobody to compare against."
            : "No other team has synced into this league yet — a trade needs two rosters."}
        </p>
      )}

      {status === "ready" && trades && opponents.length > 0 && (
        <TradesContent
          trades={trades}
          partnerName={
            opponents.find((team) => team.team_id === selectedTeamId)?.name ?? "the other team"
          }
          onRefresh={handleRefresh}
        />
      )}
    </main>
  );
}

/**
 * Copy for an empty proposal list. The three cases are genuinely different
 * answers and must not share a sentence: "nothing spare" and "nothing weak"
 * are opposite pieces of advice (one says trade for depth, the other says
 * you have no need to fix), and saying "balanced build" when only one of them
 * holds tells the user something false about their own roster.
 */
function emptyProposalCopy(trades: LeagueTradesResponse): string {
  const noSurplus = trades.mine.surplus.length === 0;
  const noDeficit = trades.mine.deficit.length === 0;
  if (noSurplus && noDeficit) {
    return "Nothing to propose: your roster has no clear tradeable surplus and no clear weakness to fix. That's a balanced build, not an error.";
  }
  if (noSurplus) {
    return "Nothing to propose: you have real weaknesses, but nothing spare to trade away — every category you're strong in rests on a single player, so dealing them would collapse it rather than trim it. The waiver wire is the better route here.";
  }
  if (noDeficit) {
    return "Nothing to propose: you have depth to spare but no category weak enough to be worth fixing by trade.";
  }
  return "No combination helped both rosters. Every swap examined either failed to fix a real weakness for one side, or collapsed a category the other side is strong in.";
}

function TradesContent({
  trades,
  partnerName,
  onRefresh,
}: {
  trades: LeagueTradesResponse;
  partnerName: string;
  onRefresh: () => Promise<void>;
}) {
  return (
    <div className="mt-8 space-y-10">
      {trades.stale && <StaleBanner syncedAt={trades.synced_at} onRefresh={onRefresh} />}

      {/* freshness is shown always, not only when stale: this page advises a
          decision the user cannot undo, so how old the rosters are is part of
          the advice. Matchup and Adds both do the same. */}
      <p className="font-mono text-xs uppercase tracking-wide text-ink/70">
        Rosters as of {formatSyncedAt(trades.synced_at)}
      </p>

      <section aria-labelledby="proposals-heading">
        <h2 id="proposals-heading" className="font-display text-xl text-ink">
          Proposed trades with {partnerName}
        </h2>
        <p className="mt-1 text-sm text-ink/80">
          Ranked by how much they fix your weakest categories.
        </p>

        <div className="mt-3">
          <ValueBasisNotice
            valueBasis={trades.value_basis}
            evaluated={trades.evaluated}
            truncated={trades.truncated}
            hasProposals={trades.verdicts.length > 0}
          />
        </div>

        {trades.verdicts.length > 0 ? (
          <>
            <div className="mt-4">
              <ExplanationsNotice
                explanations={trades.explanations}
                reason={trades.explanations_reason}
              />
            </div>
            <ol className="mt-4 space-y-6">
              {trades.verdicts.map((verdict, i) => {
                // a proposal has no player key of its own, so the advisor keys
                // it by the engine's ranking position -- see the trades builder
                // in api/routes.py
                const itemKey = `proposal-${i}`;
                return (
                  <li key={`${verdict.give.join("-")}|${verdict.get.join("-")}`}>
                    <TradeCard verdict={verdict} rank={i + 1} players={trades.players} />
                    <ModelReasoning
                      reasoning={reasoningByItemKey(trades.explanations).get(itemKey)}
                      modelRank={modelRankByItemKey(trades.explanations).get(itemKey)}
                      engineRank={i + 1}
                    />
                  </li>
                );
              })}
            </ol>
          </>
        ) : (
          <p className="mt-4 border border-dashed border-rule px-4 py-6 text-center text-ink/80">
            {emptyProposalCopy(trades)}
          </p>
        )}
      </section>

      <section aria-labelledby="strengths-heading">
        <h2 id="strengths-heading" className="font-display text-xl text-ink">
          What each roster has spare
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-ink/80">
          A category is only tradeable surplus when more than one player carries it. Strong on one
          player&apos;s back is fragile — trading them collapses the category rather than trimming
          it.
        </p>
        {/* stacked, not side by side: two nine-row tables at half of this
            column's width force a horizontal scroll on an ordinary desktop */}
        <div className="mt-4 space-y-6">
          <div>
            <h3 className="font-mono text-xs uppercase tracking-wide text-ink">Your roster</h3>
            <div className="mt-2">
              <SideStrengths side={trades.mine} players={trades.players} />
            </div>
          </div>
          <div>
            <h3 className="font-mono text-xs uppercase tracking-wide text-ink">{partnerName}</h3>
            <div className="mt-2">
              <SideStrengths side={trades.theirs} players={trades.players} />
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
