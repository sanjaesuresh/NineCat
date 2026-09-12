// Pure, framework-free helpers for the live-draft polling source (WP3).
// Kept separate from useLiveDraftSession.ts because this repo's vitest config
// runs plain node (no jsdom/testing-library), so anything that needs to be
// unit-tested has to be a function, not a rendered hook -- same split the
// mock session already uses (draftSession.ts / useDraftSession.ts).

import type { DraftBoardPlayer, DraftLivePick, DraftLiveResponse } from "@/lib/api";
import type { DraftPick } from "./draftSession";

export type DraftMode = "live" | "mock";

/**
 * English labels for the raw `draft_status` contract value -- never render
 * the wire string directly (house rule: no raw contract keys on screen).
 * Keyed as a Record over the full union so a new status value landing on the
 * backend is a compile error here, not a silent raw string on the page.
 */
export const DRAFT_STATUS_LABEL: Record<DraftLiveResponse["draft_status"], string> = {
  predraft: "not started",
  draft: "in progress",
  postdraft: "complete",
};

/**
 * Decides live vs mock from a single probe of GET .../draft/live. `null`
 * covers every "no live draft available" case the caller already folded
 * together before calling this (the probe threw -- 401 yahoo_reauth_required
 * for a dev user with no Yahoo token, a 5xx, a network error, anything) so
 * this only has to reason about a successful response's own shape.
 */
export function chooseDraftMode(probe: DraftLiveResponse | null): DraftMode {
  if (!probe) return "mock";
  if (probe.draft_status === "draft") return "live";
  // a completed draft with recorded picks is worth showing as a final state;
  // an empty postdraft (draft never actually run) has nothing over the mock
  // simulator, so it falls through to mock like predraft does
  if (probe.draft_status === "postdraft" && probe.picks.length > 0) return "live";
  return "mock";
}

/** Only poll while the tab is visible and a draft is actually in progress --
 * predraft/postdraft have nothing new to fetch, and a hidden tab shouldn't
 * hammer the endpoint every 20s for nobody to see. */
export function shouldPollLiveDraft(
  draftStatus: DraftLiveResponse["draft_status"] | null,
  documentVisible: boolean,
): boolean {
  return draftStatus === "draft" && documentVisible;
}

/** Honest placeholder for a pick this endpoint could not resolve to a player
 * -- never fabricate a name for a yahoo_player_key we don't recognize. */
export function unmappedPickLabel(pick: DraftLivePick): string {
  return `Unmapped pick #${pick.pick}`;
}

// synthetic list key for a pick with no internal player_key at all -- real
// board keys never carry this prefix, so it can't collide with one
function placeholderKey(pick: DraftLivePick): string {
  return `live-unmapped-${pick.pick}`;
}

function resolveLivePick(pick: DraftLivePick, boardByKey: Map<string, DraftBoardPlayer>): DraftPick {
  if (pick.player_key) {
    const board = boardByKey.get(pick.player_key);
    if (board) return { playerKey: board.player_key, name: board.name, position: board.position };
    // mapped to an internal id, but not on this league's draftable board
    // (e.g. off the board's eligible pool) -- still an honest pick, just no
    // display name to borrow
    return { playerKey: pick.player_key, name: unmappedPickLabel(pick), position: null };
  }
  return { playerKey: placeholderKey(pick), name: unmappedPickLabel(pick), position: null };
}

export interface DerivedLivePicks {
  myPicks: DraftPick[];
  oppPicks: DraftPick[];
  // opponent picks made since the user's own last pick, in the same
  // "compact log" role DraftSessionPanel gives the mock session's
  // lastOpponentRun -- there is no local "advance" step in live mode, so
  // this is re-derived from the pick list every poll instead
  lastOpponentRun: DraftPick[];
  takenKeys: Set<string>;
}

/** Maps the endpoint's ordered picks into the shape the mock session's
 * DraftSessionPanel already knows how to render, resolving names/positions
 * off the same board the page holds (by player_key), never fabricating one. */
export function deriveLivePicks(picks: DraftLivePick[], adpPlayers: DraftBoardPlayer[]): DerivedLivePicks {
  const boardByKey = new Map(adpPlayers.map((p) => [p.player_key, p]));
  const myPicks: DraftPick[] = [];
  const oppPicks: DraftPick[] = [];
  let lastMinePick = 0;
  for (const pick of picks) {
    const resolved = resolveLivePick(pick, boardByKey);
    if (pick.is_mine) {
      myPicks.push(resolved);
      lastMinePick = Math.max(lastMinePick, pick.pick);
    } else {
      oppPicks.push(resolved);
    }
  }
  const lastOpponentRun = picks
    .filter((p) => !p.is_mine && p.pick > lastMinePick)
    .map((p) => resolveLivePick(p, boardByKey));
  const takenKeys = new Set([...myPicks, ...oppPicks].map((p) => p.playerKey));
  return { myPicks, oppPicks, lastOpponentRun, takenKeys };
}
