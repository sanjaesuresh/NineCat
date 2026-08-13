// module-level punt-selection store shared by the hero punt-builder and draft-board
// islands, ported one-to-one from the punt-chip click handler in
// frontend/public/mockups/d-retrodata.html — no shared client parent needed, both
// islands read/write this one store and re-render via usePunts().
import { useSyncExternalStore } from "react";
import type { Cat } from "./puntDraft";

const DEFAULT_PUNTS: readonly Cat[] = ["ftp", "to"];

// mutable queue of at most two selections, oldest first; a fresh array is only ever
// swapped in on an actual change so useSyncExternalStore sees a stable reference
// between renders (returning a new array every getSnapshot call causes React to loop
// with "The result of getSnapshot should be cached")
let punts: readonly Cat[] = DEFAULT_PUNTS;

const listeners = new Set<() => void>();

export function getPunts(): readonly Cat[] {
  return punts;
}

// this module is imported by server components too (via the client islands' module
// graph during SSR); useSyncExternalStore needs a snapshot that never changes across a
// single render pass, so the server snapshot is always the fixed default rather than
// whatever the shared module happened to hold from a prior request
export function getServerPunts(): readonly Cat[] {
  return DEFAULT_PUNTS;
}

/** test-only escape hatch: module state is shared across test cases, so reset it between them. */
export function resetPunts(): void {
  punts = DEFAULT_PUNTS;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Toggles one category's punt status: removes it if already punted, otherwise adds it
 * and evicts the oldest selection so the list stays at exactly two (mockup rule).
 */
export function togglePunt(cat: Cat): void {
  const next = punts.includes(cat)
    ? punts.filter((c) => c !== cat)
    : punts.length >= 2
      ? [...punts.slice(1), cat]
      : [...punts, cat];

  punts = next;
  // isolate each listener: the hero and draft-board islands each register their own
  // subscriber, so one throwing (e.g. mid-render) must not skip the other's notification
  // or escape togglePunt into the caller's click handler
  for (const listener of listeners) {
    try {
      listener();
    } catch (err) {
      console.error("puntStore: listener threw during notification", err);
    }
  }
}

// useSyncExternalStore wiring below has no executed test coverage: this repo's test
// suite runs in node with no jsdom (and none may be added), so usePunts must be
// verified manually in a real browser before shipping.
/** React hook: current punt selection, re-rendering any subscriber when it changes. */
export function usePunts(): readonly Cat[] {
  return useSyncExternalStore(subscribe, getPunts, getServerPunts);
}
