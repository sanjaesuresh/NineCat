"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  postDraftRecommend,
  isUnauthorized,
  ApiError,
  type DraftBoardPlayer,
  type DraftRecommendation,
} from "@/lib/api";
import {
  MOCK_DRAFT_TEAMS,
  mockDraftRounds,
  mulberry32,
  snakeTeamForPick,
  weightedAdpPick,
  type DraftPick,
} from "./draftSession";

type RecStatus = "loading" | "ready" | "error";

/**
 * Owns the entire mock-draft session (state lives here, in the page, not
 * inside DraftSessionPanel) so BigBoardTable can also draft players and dim
 * ones already taken -- both need the same `takenKeys`/`draftPlayer` the
 * recommendation panel uses, and a single source of truth is the only way
 * to keep the board and the session panel from disagreeing about who's gone.
 */
export function useDraftSession({
  leagueId,
  poolSize,
  adpPlayers,
  appliedPunt,
}: {
  leagueId: number;
  poolSize: number;
  adpPlayers: DraftBoardPlayer[];
  appliedPunt: string[];
}) {
  const router = useRouter();
  const rounds = mockDraftRounds(poolSize);
  const totalPicks = rounds * MOCK_DRAFT_TEAMS;

  const [mySlot, setMySlot] = useState(1);
  const [overallPick, setOverallPick] = useState(1);
  const [myPicks, setMyPicks] = useState<DraftPick[]>([]);
  const [oppPicks, setOppPicks] = useState<DraftPick[]>([]);
  // opponent picks made since the user's last turn -- rendered as a compact
  // log so the pick counter jumping "Pick 1" -> "Pick 16" isn't a mystery
  const [lastOpponentRun, setLastOpponentRun] = useState<DraftPick[]>([]);
  const [recStatus, setRecStatus] = useState<RecStatus>("loading");
  const [recommendations, setRecommendations] = useState<DraftRecommendation[]>([]);
  const [recError, setRecError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState<string | null>(null);

  // re-seeded on every startSession() call (a fresh Date.now()-derived seed)
  // so "Reset mock draft" doesn't replay an identical board, while the
  // underlying pick function stays a pure, testable function of (seed, draw)
  const rngRef = useRef<() => number>(mulberry32(1));

  const draftStarted = myPicks.length > 0 || oppPicks.length > 0;
  const draftComplete = rounds >= 1 && overallPick > totalPicks;
  const takenKeys = new Set([...myPicks, ...oppPicks].map((p) => p.playerKey));

  const fetchRecommendations = useCallback(
    async (pickNumber: number, mine: DraftPick[], opp: DraftPick[]) => {
      setRecStatus("loading");
      setRecError(null);
      try {
        const res = await postDraftRecommend(leagueId, {
          my_player_keys: mine.map((p) => p.playerKey),
          taken_player_keys: opp.map((p) => p.playerKey),
          overall_pick: pickNumber,
          punt: appliedPunt,
          limit: 5,
        });
        setRecommendations(res.recommendations);
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
    },
    [leagueId, appliedPunt, router],
  );

  // walk the local simulation past every opponent turn up to (not including)
  // the next pick that belongs to mySlot, each opponent drawing a
  // weighted-random pick off the top of the canonical (unpunted) ADP order
  const advanceOpponents = useCallback(
    (fromPick: number, excluded: Set<string>): { nextPick: number; picks: DraftPick[] } => {
      const picks: DraftPick[] = [];
      const taken = new Set(excluded);
      let pick = fromPick;
      while (pick <= totalPicks && snakeTeamForPick(pick, MOCK_DRAFT_TEAMS) !== mySlot) {
        const available = adpPlayers.filter((p) => !taken.has(p.player_key));
        const next = weightedAdpPick(available, rngRef.current);
        if (!next) break; // pool exhausted -- the sizing guard should prevent this
        taken.add(next.player_key);
        picks.push({ playerKey: next.player_key, name: next.name, position: next.position });
        pick++;
      }
      return { nextPick: pick, picks };
    },
    [adpPlayers, mySlot, totalPicks],
  );

  const startSession = useCallback(() => {
    rngRef.current = mulberry32(Date.now() ^ Math.floor(Math.random() * 0xffffffff));
    const { nextPick, picks } = advanceOpponents(1, new Set());
    setMyPicks([]);
    setOppPicks(picks);
    setLastOpponentRun(picks);
    setOverallPick(nextPick);
    setAnnouncement(null);
    if (rounds >= 1 && nextPick <= totalPicks) {
      fetchRecommendations(nextPick, [], picks);
    } else {
      setRecStatus("ready");
      setRecommendations([]);
    }
  }, [advanceOpponents, fetchRecommendations, rounds, totalPicks]);

  // fetch-on-mount, re-init whenever the pool/slot changes (pre-draft only),
  // and — once a session is underway — refetch advice for the CURRENT pick
  // when the applied punt changes, without resetting picks already made
  const appliedPuntKey = appliedPunt.join(",");
  useEffect(() => {
    if (myPicks.length === 0 && oppPicks.length === 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      startSession();
    } else {
      fetchRecommendations(overallPick, myPicks, oppPicks);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mySlot, poolSize, appliedPuntKey]);

  function draftPlayer(pick: DraftPick) {
    const newMine = [...myPicks, pick];
    const excluded = new Set([...myPicks, ...oppPicks, pick].map((p) => p.playerKey));
    const { nextPick, picks: newOpp } = advanceOpponents(overallPick + 1, excluded);
    const newOpponents = [...oppPicks, ...newOpp];
    setMyPicks(newMine);
    setOppPicks(newOpponents);
    setLastOpponentRun(newOpp);
    setOverallPick(nextPick);
    setAnnouncement(
      nextPick <= totalPicks
        ? `Drafted ${pick.name}. Pick ${nextPick} of ${totalPicks} is next.`
        : `Drafted ${pick.name}. Mock draft complete.`,
    );
    if (nextPick <= totalPicks) {
      fetchRecommendations(nextPick, newMine, newOpponents);
    } else {
      setRecStatus("ready");
      setRecommendations([]);
    }
  }

  return {
    rounds,
    totalPicks,
    mySlot,
    setMySlot,
    overallPick,
    myPicks,
    oppPicks,
    lastOpponentRun,
    takenKeys,
    draftStarted,
    draftComplete,
    recStatus,
    recommendations,
    recError,
    announcement,
    startSession,
    draftPlayer,
    retryRecommendations: () => fetchRecommendations(overallPick, myPicks, oppPicks),
  };
}

export type DraftSession = ReturnType<typeof useDraftSession>;
