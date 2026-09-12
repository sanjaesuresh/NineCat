"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { describePoolBasisNote } from "./tokens";
import { controlClasses, proseClasses } from "@/components/dashboard/layout/typography";
import { noticeClasses, noticeDotClasses } from "@/components/dashboard/layout/layoutTokens";

/**
 * Discloses which pool the candidates below were drawn from (WP5) --
 * Yahoo's real free-agent list, or the seeded demo pool used until one
 * exists for this league -- and, only on the live basis, the on-demand
 * resync action for it (backend/src/ninecat/api/routes.py's
 * league_adds_refresh). Rendered unconditionally above the
 * schedule_coverage branch in AddsContent, so the disclosure still reads
 * correctly whether that branch shows the ranked table, the honest "nothing
 * is worth an add" empty state, or the schedule-coverage replacement.
 */
export default function PoolBasisNotice({
  poolBasis,
  freeAgentsSyncedAt,
  onRefresh,
}: {
  poolBasis: string;
  freeAgentsSyncedAt: string | null;
  onRefresh: () => Promise<void>;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isLive = poolBasis === "live_free_agents";

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      await onRefresh();
    } catch (err) {
      // the endpoint's two documented failure modes get their own honest
      // copy; anything else falls back to StaleBanner's generic phrasing
      if (err instanceof ApiError && err.status === 401) {
        setError("Free agents didn't refresh — Yahoo needs to be reconnected before this can sync again.");
      } else if (err instanceof ApiError && err.status === 503) {
        setError("Yahoo is unavailable, showing the last synced list.");
      } else {
        setError(
          err instanceof ApiError
            ? `Refresh didn't go through (${err.status}). Try again.`
            : "Refresh didn't go through. Check your connection and try again.",
        );
      }
    } finally {
      // caller re-fetches on success; always clear the pending state so a
      // failed refresh doesn't leave the button stuck disabled
      setRefreshing(false);
    }
  }

  return (
    <div className={noticeClasses()}>
      <span className={noticeDotClasses(isLive ? "info" : "warn")} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div role="status" className="flex flex-wrap items-center justify-between gap-3">
          <p className={proseClasses()}>{describePoolBasisNote(poolBasis, freeAgentsSyncedAt)}</p>
          {isLive && (
            <button
              type="button"
              onClick={handleRefresh}
              disabled={refreshing}
              className={`shrink-0 border border-ink px-3 py-1.5 hover:bg-ink hover:text-paper disabled:cursor-not-allowed disabled:opacity-60 ${controlClasses()}`}
            >
              {refreshing ? "Refreshing…" : "Refresh free agents"}
            </button>
          )}
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
