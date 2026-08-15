"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { refreshLeague, disconnectYahoo, deleteAccount } from "@/lib/api";
import ConfirmDialog from "@/components/dashboard/ConfirmDialog";
import PageHeader from "@/components/dashboard/layout/PageHeader";
import Panel from "@/components/dashboard/layout/Panel";

type RefreshState = "idle" | "pending" | "done" | "error";

export default function SettingsPage() {
  const params = useParams<{ leagueId: string }>();
  const leagueId = Number(params.leagueId);
  const [refreshState, setRefreshState] = useState<RefreshState>("idle");

  async function handleRefresh() {
    setRefreshState("pending");
    try {
      await refreshLeague(leagueId);
      setRefreshState("done");
    } catch {
      setRefreshState("error");
    }
  }

  async function handleDisconnect() {
    await disconnectYahoo();
    // hard navigation (not router.push) is deliberate: this just invalidated the
    // session server-side, so the client needs a full reload rather than a soft
    // transition that could keep stale authenticated state around
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/";
  }

  async function handleDelete() {
    await deleteAccount();
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/";
  }

  return (
    <main className="min-w-0 w-full">
      <PageHeader title="Settings" />

      {/* Inner 640px cap on the form content only, not the page container --
          the shell already owns the 1600px page-level cap (DashboardShell.tsx),
          so this narrows just this page's own content the way a form
          benefits from a narrow measure. That's an inner cap, not a revival
          of the per-tab container-width inconsistency this redesign removed:
          no max-w- class lives on the <main> or its immediate wrapper here. */}
      <div className="mt-4 max-w-[640px] space-y-4 px-6 sm:px-10">
        {/* Panel titles below deliberately avoid the substring "Settings":
            PageHeader already renders the page's one h1 "Settings", and
            e2e/smoke.spec.ts:67 looks up a heading by that name with no
            level pinned, so any second heading whose name also contains
            "Settings" would produce two matches and fail Playwright's
            strict-mode uniqueness check. */}
        <Panel title="Refresh league data" headingId="refresh-heading">
          <p className="text-ink/90">
            Pull the latest rosters, standings, and matchup from Yahoo for this league.
          </p>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshState === "pending"}
            className="mt-4 border border-ink px-4 py-2 font-mono text-xs uppercase tracking-wide text-ink transition-colors hover:bg-ink hover:text-paper disabled:cursor-not-allowed disabled:opacity-60"
          >
            {refreshState === "pending" ? "Refreshing…" : "Refresh now"}
          </button>
          {refreshState === "done" && (
            <p role="status" className="mt-3 text-sm text-ink/90">
              Refreshed. Head back to My Team to see the latest.
            </p>
          )}
          {refreshState === "error" && (
            <p role="alert" className="mt-3 border-l-4 border-alert bg-ink/[0.03] px-3 py-2 text-sm text-ink">
              Refresh didn&apos;t go through. Try again.
            </p>
          )}
        </Panel>

        <Panel title="Disconnect Yahoo" headingId="disconnect-heading">
          <p className="text-ink/90">
            Revokes NineCat&apos;s access to your Yahoo account. You&apos;ll need to sign in
            again to reconnect.
          </p>
          <ConfirmDialog
            triggerLabel="Disconnect Yahoo"
            triggerClassName="mt-4 border border-alert px-4 py-2 font-mono text-xs uppercase tracking-wide text-ink transition-colors hover:bg-alert hover:text-paper"
            title="Disconnect Yahoo?"
            description="NineCat will lose access to your Yahoo leagues until you sign in again. This doesn't delete your NineCat account."
            confirmLabel="Disconnect"
            pendingLabel="Disconnecting…"
            danger
            onConfirm={handleDisconnect}
          />
        </Panel>

        {/* tone="destructive" (not Panel's default border-rule) marks this as
            the destructive section -- panelClasses picks the border-color
            class internally so there is exactly one per call, no className
            override or `!important` needed to win the cascade. */}
        <Panel title="Delete account" headingId="delete-heading" tone="destructive">
          <p className="text-ink/90">
            Permanently deletes your NineCat account and all synced league data. This
            can&apos;t be undone.
          </p>
          <ConfirmDialog
            triggerLabel="Delete account"
            triggerClassName="mt-4 border-2 border-alert bg-alert px-4 py-2 font-mono text-xs uppercase tracking-wide text-paper transition-colors hover:bg-paper hover:text-alert"
            title="Delete your account?"
            description="This permanently deletes your NineCat account and all synced league data. This can't be undone."
            confirmLabel="Delete account"
            pendingLabel="Deleting…"
            requirePhrase="DELETE"
            danger
            onConfirm={handleDelete}
          />
        </Panel>
      </div>
    </main>
  );
}
