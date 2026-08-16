"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { formatSyncedAt } from "./format";
import { controlClasses, eyebrowClasses, proseClasses } from "@/components/dashboard/layout/typography";
import { noticeClasses, noticeDotClasses } from "@/components/dashboard/layout/layoutTokens";

/** Shown when a data view's `stale: true` flag says the cached league data is outdated. */
export default function StaleBanner({
  syncedAt,
  onRefresh,
  variant = "banner",
}: {
  syncedAt: string;
  onRefresh: () => Promise<void>;
  /** "chip" is a compact inline row sized to sit inside a sticky PageHeader; defaults to
   * "banner" so every existing full-width caller renders unchanged. */
  variant?: "banner" | "chip";
}) {
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      await onRefresh();
    } catch (err) {
      // onRefresh (refreshLeague + re-fetch) can throw — without this catch it
      // was an unhandled rejection and the button just silently stopped spinning
      setError(
        err instanceof ApiError
          ? `Refresh didn't go through (${err.status}). Try again.`
          : "Refresh didn't go through. Check your connection and try again.",
      );
    } finally {
      // caller re-fetches on success; always clear the pending state so a
      // failed refresh doesn't leave the button stuck disabled
      setRefreshing(false);
    }
  }

  // computed once so the button's accessible name can't drift between variants —
  // e2e specs locate the refresh control by this text
  const refreshLabel = refreshing ? "Refreshing…" : "Refresh now";

  if (variant === "chip") {
    return (
      <div className="inline-flex flex-col items-start gap-1">
        <div role="status" className="inline-flex w-fit items-center gap-2 border border-amber px-2 py-1">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber" aria-hidden="true" />
          <p className={`whitespace-nowrap ${eyebrowClasses("ink")}`}>
            Stale — synced {formatSyncedAt(syncedAt)}
          </p>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className={`shrink-0 whitespace-nowrap border border-ink px-2 py-0.5 hover:bg-ink hover:text-paper disabled:cursor-not-allowed disabled:opacity-60 ${controlClasses()}`}
          >
            {refreshLabel}
          </button>
        </div>
        {error && (
          // no whitespace-nowrap here: this can run to 63 chars and must wrap inside
          // the sticky header, or it reopens the mobile horizontal-scroll bug
          <p role="alert" className="max-w-[68ch] font-body text-prose text-alert">
            {error}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className={noticeClasses()}>
      <span className={noticeDotClasses("warn")} aria-hidden="true" />
      {/* min-w-0 + flex-1: the notice container is flex for its dot, so this
          wrapper must both shrink (long sync copy) and fill the row so the
          refresh button keeps its right-aligned justify-between position */}
      <div className="min-w-0 flex-1">
        <div role="status" className="flex flex-wrap items-center justify-between gap-3">
          <p className={proseClasses()}>
            This data is stale — last synced {formatSyncedAt(syncedAt)}.
          </p>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className={`shrink-0 border border-ink px-3 py-1.5 hover:bg-ink hover:text-paper disabled:cursor-not-allowed disabled:opacity-60 ${controlClasses()}`}
          >
            {refreshLabel}
          </button>
        </div>
        {error && (
          <p role="alert" className={`mt-3 ${noticeClasses()} ${proseClasses()}`}>
            <span className={noticeDotClasses("error")} aria-hidden="true" />
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
