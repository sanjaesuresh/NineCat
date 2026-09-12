"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getDraftLive,
  postDraftRecommend,
  isUnauthorized,
  ApiError,
  type DraftBoardPlayer,
  type DraftLiveResponse,
  type DraftRecommendation,
  type ModelExplanations,
} from "@/lib/api";
import { deriveLivePicks, shouldPollLiveDraft } from "./liveDraftSession";

type RecStatus = "loading" | "ready" | "error";

const POLL_MS = 20_000;

/**
 * Live counterpart to useDraftSession (WP3): reads Yahoo's draft state
 * through the polled /draft/live endpoint instead of running a local
 * simulation, but returns the exact same DraftSession shape so
 * DraftSessionPanel needs zero changes. The Draft page uses this hook's
 * `probed`/`live` fields (via liveDraftSession.ts's chooseDraftMode) to
 * decide whether to render this session or the mock one -- this hook itself
 * always runs its fetch-on-mount regardless of the eventual mode, since that
 * first fetch IS the probe the mode decision reads.
 */
export function useLiveDraftSession({
  leagueId,
  adpPlayers,
  appliedPunt,
}: {
  leagueId: number;
  adpPlayers: DraftBoardPlayer[];
  appliedPunt: string[];
}) {
  const router = useRouter();

  const [live, setLive] = useState<DraftLiveResponse | null>(null);
  // true once the first fetch has settled (success or failure) -- distinct
  // from `live` being null, which after the first attempt genuinely means
  // "no live draft" (mock mode), not "still finding out"
  const [probed, setProbed] = useState(false);

  const [recStatus, setRecStatus] = useState<RecStatus>("loading");
  const [recommendations, setRecommendations] = useState<DraftRecommendation[]>([]);
  const [explanations, setExplanations] = useState<ModelExplanations | null>(null);
  const [explanationsReason, setExplanationsReason] = useState<string | null>(null);
  const [recError, setRecError] = useState<string | null>(null);

  const fetchLive = useCallback(async () => {
    try {
      const res = await getDraftLive(leagueId);
      setLive(res);
    } catch {
      // Every non-200 here means "no live draft available" per the backend
      // contract -- including 401 yahoo_reauth_required for a dev user with
      // no Yahoo token, which is the expected/normal case for local dev, NOT
      // a session-expired signal. Deliberately does not use isUnauthorized ->
      // redirect-to-"/" the way every other fetcher in this app does.
      //
      // On a failure AFTER the first probe (a transient poll blip mid-draft),
      // leave `live` at its last-known value instead of nulling it out --
      // otherwise one dropped poll would silently kick an active draft back
      // to mock mode and tear down the poll interval (see the effect below).
    } finally {
      setProbed(true);
    }
  }, [leagueId]);

  // one immediate fetch on mount -- this doubles as the page's live/mock probe
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchLive();
  }, [fetchLive]);

  const draftStatus = live?.draft_status ?? null;

  // poll only while a draft is actually in progress -- predraft/postdraft
  // have nothing new to fetch, so the interval is never even created for
  // them (satisfies "stop entirely on postdraft" for free: once a poll
  // response flips draftStatus away from "draft", this effect's cleanup
  // runs and it does not re-arm). Each tick still re-checks visibility
  // itself (pause), and a visibilitychange back to visible fires one
  // immediate catch-up fetch (resume) rather than waiting up to 20s.
  useEffect(() => {
    if (draftStatus !== "draft") return;
    const tick = () => {
      if (shouldPollLiveDraft(draftStatus, document.visibilityState === "visible")) {
        fetchLive();
      }
    };
    const id = setInterval(tick, POLL_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [draftStatus, fetchLive]);

  const { myPicks, oppPicks, lastOpponentRun, takenKeys } = deriveLivePicks(
    live?.picks ?? [],
    adpPlayers,
  );
  const overallPick = live?.overall_pick ?? 1;

  const fetchRecommendations = useCallback(async () => {
    setRecStatus("loading");
    setRecError(null);
    try {
      const res = await postDraftRecommend(leagueId, {
        my_player_keys: myPicks.map((p) => p.playerKey),
        taken_player_keys: oppPicks.map((p) => p.playerKey),
        overall_pick: overallPick,
        punt: appliedPunt,
        limit: 5,
      });
      setRecommendations(res.recommendations);
      setExplanations(res.explanations);
      setExplanationsReason(res.explanations_reason);
      setRecStatus("ready");
    } catch (err) {
      if (isUnauthorized(err)) {
        router.replace("/");
        return;
      }
      setRecError(
        err instanceof ApiError
          ? `Couldn't load recommendations (${err.status}).`
          : "Couldn't reach NineCat. Check your connection and try again.",
      );
      setRecStatus("error");
    }
  }, [leagueId, appliedPunt, router, myPicks, oppPicks, overallPick]);

  // refetch recommendations whenever the taken/mine sets change (a new pick
  // landed on a poll) or the punt build changes, same triggers the mock hook
  // uses. Skipped entirely outside an active draft: predraft is never
  // rendered (page picks mock mode instead) and postdraft has no next pick
  // to recommend -- so this never spends a network call either state.
  const takenKey = [...myPicks.map((p) => p.playerKey), "|", ...oppPicks.map((p) => p.playerKey)].join(",");
  const appliedPuntKey = appliedPunt.join(",");
  useEffect(() => {
    if (draftStatus !== "draft") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRecStatus("ready");
      setRecommendations([]);
      setExplanations(null);
      setExplanationsReason(null);
      return;
    }
    fetchRecommendations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftStatus, takenKey, appliedPuntKey]);

  return {
    // DraftSession shape -- DraftSessionPanel and the page's shared bits read
    // these with zero knowledge of which hook produced them
    rounds: 1, // live mode has no local pool-size gate; always "enough"
    totalPicks: live?.picks.length ?? 0, // only ever shown once draftComplete
    mySlot: live?.my_slot ?? 0,
    // the slot picker is hidden entirely in live mode (state comes from
    // Yahoo) -- this is a structural no-op to satisfy the shared shape
    setMySlot: () => {},
    overallPick,
    myPicks,
    oppPicks,
    lastOpponentRun,
    takenKeys,
    draftStarted: (live?.picks.length ?? 0) > 0,
    draftComplete: draftStatus === "postdraft",
    recStatus,
    recommendations,
    explanations,
    explanationsReason,
    recError,
    // never set: DraftSessionPanel moves focus to the "on the clock" heading
    // on every announcement change, which is right for a mock pick the user
    // just clicked but would be an unsolicited focus steal every ~20s poll
    // tick here -- silence is the safer a11y choice for a passive update
    announcement: null as string | null,
    // picks happen in Yahoo's draft room, not here -- both are no-ops
    startSession: () => {},
    draftPlayer: () => {},
    retryRecommendations: fetchRecommendations,

    // extras the Draft page needs that DraftSessionPanel doesn't
    live,
    probed,
    draftStatus,
    stale: live?.stale ?? false,
    unmappedCount: live?.unmapped.length ?? 0,
    lastSyncedAt: live?.synced_at ?? null,
  };
}
