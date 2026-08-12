"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { refreshLeague, disconnectYahoo, deleteAccount } from "@/lib/api";
import ConfirmDialog from "@/components/dashboard/ConfirmDialog";

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
    <main className="mx-auto min-w-0 w-full max-w-4xl px-6 py-10 sm:px-10 sm:py-14">
      <h1 className="font-display text-3xl font-semibold text-ink">Settings</h1>

      <section className="mt-8 border border-rule p-5" aria-labelledby="refresh-heading">
        <h2 id="refresh-heading" className="font-display text-lg font-semibold text-ink">
          Refresh league data
        </h2>
        <p className="mt-1 max-w-prose text-ink/90">
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
      </section>

      <section className="mt-6 border border-rule p-5" aria-labelledby="disconnect-heading">
        <h2 id="disconnect-heading" className="font-display text-lg font-semibold text-ink">
          Disconnect Yahoo
        </h2>
        <p className="mt-1 max-w-prose text-ink/90">
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
      </section>

      <section className="mt-6 border border-alert p-5" aria-labelledby="delete-heading">
        <h2 id="delete-heading" className="font-display text-lg font-semibold text-ink">
          Delete account
        </h2>
        <p className="mt-1 max-w-prose text-ink/90">
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
      </section>
    </main>
  );
}
