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
import { SkeletonCard, SkeletonStatRow, SkeletonTable } from "@/components/dashboard/Skeletons";
import BigBoardTable from "@/components/dashboard/draft/BigBoardTable";
import PuntSuggestions from "@/components/dashboard/draft/PuntSuggestions";
import DraftSessionPanel from "@/components/dashboard/draft/DraftSessionPanel";
import { useDraftSession } from "@/components/dashboard/draft/useDraftSession";
import { MOCK_DRAFT_TEAMS, type DraftPick } from "@/components/dashboard/draft/draftSession";
import PageHeader from "@/components/dashboard/layout/PageHeader";
import Panel from "@/components/dashboard/layout/Panel";
import StatRow from "@/components/dashboard/layout/StatRow";
import StatTile from "@/components/dashboard/layout/StatTile";
import { deriveDraftStats } from "@/components/dashboard/stats/deriveDraftStats";
import { captionClasses, controlClasses, proseClasses, uiTextClasses } from "@/components/dashboard/layout/typography";
import { emptyStateClasses, noticeClasses, noticeDotClasses, pageStackClasses } from "@/components/dashboard/layout/layoutTokens";

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
  // "your build" section, not a whole-page 404
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

  // every tile comes from state this page already holds -- no new fetch;
  // only meaningful once the board has loaded (mirrors the mock-draft
  // controls' own rounds >= 1 gate below). `session.draftComplete` is passed
  // through so deriveDraftStats can null out pick/round once the draft is
  // done -- overallPick overshoots totalPicks by design at that point (see
  // useDraftSession), so there's no valid "N of M" to show.
  const draftStats =
    status === "ready" && board
      ? deriveDraftStats({
          overallPick: session.overallPick,
          totalPicks: session.totalPicks,
          teams: MOCK_DRAFT_TEAMS,
          poolSize,
          appliedPunt,
          complete: session.draftComplete,
        })
      : null;

  // single gate for both Pick/Round tiles (collapses what used to be a
  // separate `rounds >= 1` check duplicated on each tile): they're only
  // meaningful mid-draft -- hidden before the pool supports a full round,
  // and hidden again once complete (deriveDraftStats already nulls the
  // values for that case, but the boolean here avoids passing `null` into a
  // rendered tile in the first place)
  const showPickRoundTiles = session.rounds >= 1 && !session.draftComplete;

  // the slot select used to live inside DraftSessionPanel; it moves up here
  // so it can render in PageHeader's sticky actions slot. Gated the same way
  // DraftSessionPanel itself gates its controls -- hidden until the board is
  // ready and the pool supports at least one round -- so a locked/disabled
  // select never appears before there's a session to lock. The reset button
  // stays inside DraftSessionPanel (see that file's docstring): e2e/draft.spec.ts
  // scopes its "Reset mock draft" locator to `section:has(#session-heading)`,
  // so it must remain a descendant of that section, not PageHeader.
  const showSessionControls = status === "ready" && session.rounds >= 1;

  return (
    <main className="min-w-0 w-full">
      <PageHeader
        title="Draft"
        actions={
          showSessionControls ? (
            <>
              <label className={`flex items-center gap-2 ${controlClasses("muted")}`}>
                Your slot
                <select
                  value={session.mySlot}
                  disabled={session.draftStarted}
                  onChange={(e) => session.setMySlot(Number(e.target.value))}
                  title={
                    session.draftStarted
                      ? "Locked once the mock draft starts — reset it in Mock draft & recommendations, below"
                      : undefined
                  }
                  className={`border border-ink bg-paper px-3 py-1.5 ${uiTextClasses()} disabled:cursor-not-allowed disabled:opacity-60`}
                >
                  {Array.from({ length: MOCK_DRAFT_TEAMS }, (_, i) => i + 1).map((slot) => (
                    <option key={slot} value={slot}>
                      {slot} of {MOCK_DRAFT_TEAMS}
                    </option>
                  ))}
                </select>
              </label>
              {session.draftStarted && (
                <span className={captionClasses()}>
                  Locked — reset in Mock draft &amp; recommendations, below
                </span>
              )}
            </>
          ) : undefined
        }
      />

      <div className={pageStackClasses()}>
        {status === "loading" && (
          <div aria-busy="true">
            <p role="status" className="sr-only">
              Loading draft board…
            </p>
            {/* mirrors the real ready-state order below (session, punt,
                build, board) so nothing reflows/reorders once data lands */}
            <div className="space-y-4">
              <SkeletonStatRow tiles={4} />
              <SkeletonCard lines={4} />
              <SkeletonCard lines={2} />
              <SkeletonCard lines={2} />
              <SkeletonTable rows={8} cols={14} />
            </div>
          </div>
        )}

        {status === "error" && (
          <Panel title="Draft status">
            <ErrorState message={errorMessage ?? undefined} onRetry={loadBoard} />
          </Panel>
        )}

        {status === "ready" && board && baseBoard && (
          <>
            {stale && syncedAt && <StaleBanner syncedAt={syncedAt} onRefresh={handleRefresh} />}

            {draftStats && (
              <StatRow>
                {showPickRoundTiles && <StatTile label="Pick" value={draftStats.pick} />}
                {showPickRoundTiles && <StatTile label="Round" value={draftStats.round} />}
                <StatTile
                  label="Pool size"
                  value={draftStats.pool}
                  sub="Full draftable board — doesn't shrink as picks are made"
                />
                <StatTile
                  label="Punt build"
                  value={draftStats.puntLabels.length > 0 ? draftStats.puntLabels.join(" + ") : "None"}
                />
              </StatRow>
            )}

            {/* stacked, full-width panels, in priority order -- restores the
                original page's ordering (the recommendation engine is the
                product: it comes first, well above the 72-row board, which
                is reference material by comparison). The prior regrid paired
                the board with a 360px right rail for recommendations, which
                doesn't work at any width this page ships at: the rail (360px)
                plus its gap and the panel's own padding was too narrow for a
                recommendation card's own content, and it took exactly that
                much width away from the board, leaving no room for its 980px
                min-width table without horizontal scroll. See BigBoardTable's
                docstring for that table's own min-width contract. */}
            <Panel title="Mock draft & recommendations" headingId="session-heading">
              <DraftSessionPanel session={session} adpPlayers={adpPlayers} />
            </Panel>

            <Panel title="Punt suggestions" headingId="punt-heading">
              <PuntSuggestions
                suggestions={board.punt_suggestions}
                applied={appliedPunt}
                pendingPunt={pendingPunt}
                error={puntError}
                onSelect={syncBoard}
                onClear={() => syncBoard([])}
              />
            </Panel>

            <Panel title="Your build" headingId="build-heading">
              {teamStatus === "loading" && <SkeletonCard lines={2} />}
              {teamStatus === "unclaimed" && (
                <p className={emptyStateClasses()}>
                  You haven&apos;t claimed a team in this league yet — the board still works;
                  punt suggestions need a roster.
                </p>
              )}
              {teamStatus === "error" && (
                <ErrorState message="Couldn't load your build." onRetry={loadTeam} />
              )}
              {teamStatus === "ready" && team && <BuildProfile profile={team.build_profile} />}
            </Panel>

            {/* flush: no inner padding, so BigBoardTable's 980px-min table
                gets the panel's full width instead of losing 32px to it --
                see BigBoardTable's docstring for how it owns its own inset
                on the descriptive text above the table */}
            <Panel title="Big board" headingId="board-heading" flush>
              {(appliedPunt.length > 0 || pendingPunt !== null || puntError) && (
                <div className="space-y-3 px-4 pt-4 pb-3">
                  {appliedPunt.length > 0 && (
                    <div className={noticeClasses()}>
                      <span className={noticeDotClasses("warn")} aria-hidden="true" />
                      {/* flex-1 so justify-between still pushes the clear
                          button to the notice's right edge beside the dot */}
                      <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-3">
                        <p className={proseClasses()}>
                          Board adjusted for punt: {draftStats?.puntLabels.join(", ")} — value
                          excludes these categories.
                        </p>
                        <button
                          type="button"
                          onClick={() => syncBoard([])}
                          disabled={pendingPunt !== null}
                          aria-busy={pendingPunt?.length === 0}
                          className={`shrink-0 border border-ink px-3 py-1.5 hover:bg-ink hover:text-paper disabled:cursor-not-allowed disabled:opacity-60 ${controlClasses()}`}
                        >
                          {pendingPunt?.length === 0 ? "Clearing…" : "Clear punt"}
                        </button>
                      </div>
                    </div>
                  )}
                  {pendingPunt !== null && (
                    <p role="status" className={proseClasses("muted")}>
                      Re-ranking board…
                    </p>
                  )}
                  {puntError && (
                    <p
                      role="alert"
                      className={`${noticeClasses()} ${proseClasses()}`}
                    >
                      <span className={noticeDotClasses("error")} aria-hidden="true" />
                      {puntError}
                    </p>
                  )}
                </div>
              )}

              <BigBoardTable
                players={board.players}
                source={board.source}
                takenKeys={session.takenKeys}
                onDraft={draftFromBoard}
                puntPending={pendingPunt !== null}
              />
            </Panel>
          </>
        )}
      </div>
    </main>
  );
}
