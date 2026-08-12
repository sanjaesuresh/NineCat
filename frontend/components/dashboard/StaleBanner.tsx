"use client";

import { useState } from "react";
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

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      // caller re-fetches on success; always clear the pending state so a
      // failed refresh doesn't leave the button stuck disabled
      setRefreshing(false);
    }
  }

  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-3 border-l-4 border-amber bg-ink/[0.03] px-4 py-3"
    >
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
  );
}
