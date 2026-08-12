"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { formatSyncedAt } from "./format";

/** Shown when a data view's `stale: true` flag says the cached league data is outdated. */
export default function StaleBanner({
  syncedAt,
  onRefresh,
}: {
  syncedAt: string;
  onRefresh: () => Promise<void>;
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

  return (
    <div className="border-l-4 border-amber bg-ink/[0.03] px-4 py-3">
      <div role="status" className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink">
          This data is stale — last synced {formatSyncedAt(syncedAt)}.
        </p>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing}
          className="shrink-0 border border-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wide text-ink transition-colors hover:bg-ink hover:text-paper disabled:cursor-not-allowed disabled:opacity-60"
        >
          {refreshing ? "Refreshing…" : "Refresh now"}
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-3 border-l-4 border-alert bg-ink/[0.03] px-3 py-2 text-sm text-ink">
          {error}
        </p>
      )}
    </div>
  );
}
