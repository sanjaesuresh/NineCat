"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  getDraftBoard,
  getLeagueTeam,
  refreshLeague,
  isUnauthorized,
  ApiError,
  type DraftBoardPlayer,
  type DraftBoardResponse,
  type LeagueTeamResponse,
} from "@/lib/api";
import BuildProfile from "@/components/dashboard/BuildProfile";
import StaleBanner from "@/components/dashboard/StaleBanner";
import ErrorState from "@/components/dashboard/ErrorState";
import { SkeletonCard, SkeletonTable } from "@/components/dashboard/Skeletons";
import { LABEL_BY_CONTRACT_KEY } from "@/components/dashboard/categoryKeys";
import BigBoardTable from "@/components/dashboard/draft/BigBoardTable";
import PuntSuggestions from "@/components/dashboard/draft/PuntSuggestions";
import DraftSessionPanel from "@/components/dashboard/draft/DraftSessionPanel";
import { useDraftSession } from "@/components/dashboard/draft/useDraftSession";
import type { DraftPick } from "@/components/dashboard/draft/draftSession";

type Status = "loading" | "ready" | "error";
type TeamStatus = "loading" | "ready" | "unclaimed" | "error";

export default function DraftPage() {
  const params = useParams<{ leagueId: string }>();
  const router = useRouter();
  const leagueId = Number(params.leagueId);

  const [status, setStatus] = useState<Status>("loading");
  // `board` is the display board (re-fetched punt/roster-adjusted); `baseBoard`
  // is fetched once, unpunted, and used only as the mock draft's canonical
  // ADP order -- a punt is the user's own strategy, not an assumption about
  // how the rest of the field drafts (plan D3)
  const [board, setBoard] = useState<DraftBoardResponse | null>(null);
  const [baseBoard, setBaseBoard] = useState<DraftBoardResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // the team fetch is independent of the board -- a user with no claimed
  // team in this league must still get a working draft board, just an empty
  // "your build" section, not a whole-page 404 (review fix)
  const [team, setTeam] = useState<LeagueTeamResponse | null>(null);
  const [teamStatus, setTeamStatus] = useState<TeamStatus>("loading");

  const [appliedPunt, setAppliedPunt] = useState<string[]>([]);
  // null = idle; [] = clearing; non-empty = applying that specific punt --
  // drives per-button "Applying…" feedback in PuntSuggestions
  const [pendingPunt, setPendingPunt] = useState<string[] | null>(null);
  const [puntError, setPuntError] = useState<string | null>(null);

  const loadBoard = useCallback(async () => {
    if (!Number.isFinite(leagueId)) {
      setErrorMessage("This league link looks invalid.");
      setStatus("error");
      return;
    }
    setStatus("loading");
    setErrorMessage(null);
    try {
      const boardRes = await getDraftBoard(leagueId);
      setBoard(boardRes);
      setBaseBoard(boardRes);
      setAppliedPunt([]);
      setStatus("ready");
    } catch (err) {
      if (isUnauthorized(err)) {
        router.replace("/");
        return;
      }
      setErrorMessage(
        err instanceof ApiError
          ? `Couldn't load the draft board (${err.status}).`
          : "Couldn't reach NineCat. Check your connection and try again.",
      );
      setStatus("error");
    }
  }, [leagueId, router]);

  const loadTeam = useCallback(async () => {
    if (!Number.isFinite(leagueId)) return;
    setTeamStatus("loading");
    try {
      const teamRes = await getLeagueTeam(leagueId);
      setTeam(teamRes);
      setTeamStatus("ready");
    } catch (err) {
      if (isUnauthorized(err)) {
        router.replace("/");
        return;
      }
      if (err instanceof ApiError && err.status === 404) {
        // no team claimed in this league yet -- not an error, just an empty state
        setTeam(null);
        setTeamStatus("unclaimed");
      } else {
        setTeam(null);
        setTeamStatus("error");
      }
    }
  }, [leagueId, router]);

  useEffect(() => {
    // standard fetch-on-mount: these only set the status useState already initializes to
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadBoard();
    loadTeam();
  }, [loadBoard, loadTeam]);

  async function handleRefresh() {
    await refreshLeague(leagueId);
    await loadBoard();
    await loadTeam();
  }

  const poolSize = board?.players.length ?? 0;
  const adpPlayers = useMemo(() => baseBoard?.players ?? [], [baseBoard]);

  // owns the whole mock-draft session (picks, opponent simulation,
  // recommendations) -- lifted up here, not inside DraftSessionPanel, so
  // BigBoardTable can also draft players and mark ones already taken
  const session = useDraftSession({ leagueId, poolSize, adpPlayers, appliedPunt });

  // punt suggestions should reflect the roster actually being assembled in
  // the mock draft (myPlayerKeys), not just an empty/pre-season Yahoo roster
  // -- re-sync whenever the punt OR the mock draft's own picks change
  const myPlayerKeys = useMemo(() => session.myPicks.map((p) => p.playerKey), [session.myPicks]);
  const myPlayerKeysKey = myPlayerKeys.join(",");

  const syncBoard = useCallback(
    async (punt: string[]) => {
      if (punt.length === 0 && myPlayerKeys.length === 0) {
        // no adjustment needed -- baseBoard already IS this exact board
        if (baseBoard) setBoard(baseBoard);
        setAppliedPunt([]);
        setPuntError(null);
        return;
      }
      setPendingPunt(punt);
      setPuntError(null);
      try {
        const res = await getDraftBoard(leagueId, { punt, myPlayerKeys });
        setBoard(res);
        setAppliedPunt(punt);
      } catch (err) {
        if (isUnauthorized(err)) {
          router.replace("/");
          return;
        }
        setPuntError(
          err instanceof ApiError
            ? `Couldn't apply that punt build (${err.status}).`
            : "Couldn't apply that punt build. Check your connection and try again.",
        );
      } finally {
        setPendingPunt(null);
      }
    },
    [baseBoard, leagueId, myPlayerKeys, router],
  );

  // re-sync the board (and its punt suggestions) whenever the mock draft's
  // roster changes, keeping the current punt selection applied
  useEffect(() => {
    if (status !== "ready") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    syncBoard(appliedPunt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [myPlayerKeysKey]);

  function draftFromBoard(player: DraftBoardPlayer) {
    const pick: DraftPick = { playerKey: player.player_key, name: player.name, position: player.position };
    session.draftPlayer(pick);
  }

  const stale = Boolean(board?.stale || team?.stale);
  const syncedAt = board?.synced_at ?? team?.synced_at ?? null;

  const puntLabels = useMemo(
    () => appliedPunt.map((key) => LABEL_BY_CONTRACT_KEY[key] ?? key),
    [appliedPunt],
  );

  return (
    <main className="mx-auto min-w-0 w-full max-w-6xl px-6 py-10 sm:px-10 sm:py-14">
      <h1 className="font-display text-3xl text-ink">Draft</h1>

      {status === "loading" && (
        <div className="mt-8 space-y-8" aria-busy="true">
          <p role="status" className="sr-only">
            Loading draft board…
          </p>
          <SkeletonCard lines={4} />
          <SkeletonCard lines={2} />
          <SkeletonTable rows={8} cols={14} />
        </div>
      )}

      {status === "error" && (
        <div className="mt-8">
          <ErrorState message={errorMessage ?? undefined} onRetry={loadBoard} />
        </div>
      )}

      {status === "ready" && board && baseBoard && (
        <div className="mt-8 space-y-10">
          {stale && syncedAt && <StaleBanner syncedAt={syncedAt} onRefresh={handleRefresh} />}

          {/* the recommendation engine is the product -- it comes first, well
              above the 72-row board, which is reference material by comparison */}
          <section aria-labelledby="session-heading">
            <h2 id="session-heading" className="font-display text-xl text-ink">
              Mock draft &amp; recommendations
            </h2>
            <div className="mt-3">
              <DraftSessionPanel session={session} adpPlayers={adpPlayers} />
            </div>
          </section>

          <section aria-labelledby="punt-heading">
            <h2 id="punt-heading" className="font-display text-xl text-ink">
              Punt suggestions
            </h2>
            <div className="mt-3">
              <PuntSuggestions
                suggestions={board.punt_suggestions}
                applied={appliedPunt}
                pendingPunt={pendingPunt}
                error={puntError}
                onSelect={syncBoard}
                onClear={() => syncBoard([])}
              />
            </div>
          </section>

          <section aria-labelledby="build-heading">
            <h2 id="build-heading" className="font-display text-xl text-ink">
              Your build
            </h2>
            <div className="mt-3">
              {teamStatus === "loading" && <SkeletonCard lines={2} />}
              {teamStatus === "unclaimed" && (
                <p className="border border-dashed border-rule px-4 py-6 text-center text-ink/80">
                  You haven&apos;t claimed a team in this league yet — the board still works;
                  punt suggestions need a roster.
                </p>
              )}
              {teamStatus === "error" && (
                <ErrorState message="Couldn't load your build." onRetry={loadTeam} />
              )}
              {teamStatus === "ready" && team && <BuildProfile profile={team.build_profile} />}
            </div>
          </section>

          <section aria-labelledby="board-heading">
            <h2 id="board-heading" className="font-display text-xl text-ink">
              Big board
            </h2>

            {appliedPunt.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-l-4 border-amber bg-ink/[0.03] px-4 py-2">
                <p className="text-sm text-ink">
                  Board adjusted for punt: {puntLabels.join(", ")} — value excludes these
                  categories.
                </p>
                <button
                  type="button"
                  onClick={() => syncBoard([])}
                  disabled={pendingPunt !== null}
                  aria-busy={pendingPunt?.length === 0}
                  className="shrink-0 border border-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wide text-ink transition-colors hover:bg-ink hover:text-paper disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {pendingPunt?.length === 0 ? "Clearing…" : "Clear punt"}
                </button>
              </div>
            )}
            {pendingPunt !== null && (
              <p role="status" className="mt-3 text-sm text-ink/70">
                Re-ranking board…
              </p>
            )}
            {puntError && (
              <p
                role="alert"
                className="mt-3 border-l-4 border-alert bg-ink/[0.03] px-3 py-2 text-sm text-ink"
              >
                {puntError}
              </p>
            )}

            <div className="mt-3">
              <BigBoardTable
                players={board.players}
                source={board.source}
                takenKeys={session.takenKeys}
                onDraft={draftFromBoard}
                puntPending={pendingPunt !== null}
              />
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
