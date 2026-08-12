"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getMe, syncLeagues, isUnauthorized, ApiError, type League } from "@/lib/api";
import LeaguePickerCard from "@/components/dashboard/LeaguePickerCard";
import ErrorState from "@/components/dashboard/ErrorState";
import LogoutButton from "@/components/dashboard/LogoutButton";
import { SkeletonCard } from "@/components/dashboard/Skeletons";

type Status = "loading" | "syncing" | "empty" | "picker" | "error";

export default function DashboardHome() {
  const router = useRouter();
  const [status, setStatus] = useState<Status>("loading");
  const [leagues, setLeagues] = useState<League[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // React 19 dev double-invokes effects; this guards the one-time auto-sync
  // from firing the POST /api/sync request twice on mount.
  const hasAutoSynced = useRef(false);

  async function load() {
    setStatus("loading");
    setErrorMessage(null);
    try {
      const me = await getMe();
      await resolve(me.leagues);
    } catch (err) {
      handleError(err);
    }
  }

  async function resolve(current: League[]) {
    if (current.length === 1) {
      router.replace(`/dashboard/${current[0].id}`);
      return;
    }
    if (current.length > 1) {
      setLeagues(current);
      setStatus("picker");
      return;
    }
    // zero leagues: try one automatic sync before showing the empty state —
    // covers the common case of a first-time sign-in that hasn't synced yet
    if (hasAutoSynced.current) {
      setStatus("empty");
      return;
    }
    hasAutoSynced.current = true;
    setStatus("syncing");
    try {
      const synced = await syncLeagues();
      if (synced.length === 1) {
        router.replace(`/dashboard/${synced[0].id}`);
      } else if (synced.length > 1) {
        setLeagues(synced);
        setStatus("picker");
      } else {
        setStatus("empty");
      }
    } catch (err) {
      handleError(err);
    }
  }

  function handleError(err: unknown) {
    if (isUnauthorized(err)) {
      router.replace("/");
      return;
    }
    setErrorMessage(
      err instanceof ApiError
        ? `Couldn't load your leagues (${err.status}).`
        : "Couldn't reach NineCat. Check your connection and try again.",
    );
    setStatus("error");
  }

  async function handleManualSync() {
    setStatus("syncing");
    setErrorMessage(null);
    try {
      const synced = await syncLeagues();
      await resolveAfterManualSync(synced);
    } catch (err) {
      handleError(err);
    }
  }

  async function resolveAfterManualSync(synced: League[]) {
    if (synced.length === 1) {
      router.replace(`/dashboard/${synced[0].id}`);
    } else if (synced.length > 1) {
      setLeagues(synced);
      setStatus("picker");
    } else {
      setStatus("empty");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load() only needs to run once on mount
  }, []);

  return (
    <main className="mx-auto max-w-4xl px-6 py-14 sm:px-10 sm:py-20">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="font-display text-3xl font-semibold text-ink">Your leagues</h1>
        <LogoutButton />
      </div>

      {(status === "loading" || status === "syncing") && (
        <div className="mt-8 space-y-4">
          <p className="font-mono text-xs uppercase tracking-wide text-ink/70">
            {status === "syncing" ? "Syncing with Yahoo…" : "Loading…"}
          </p>
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {status === "error" && (
        <div className="mt-8">
          <ErrorState message={errorMessage ?? undefined} onRetry={load} />
        </div>
      )}

      {status === "empty" && (
        <div className="mt-8 border border-dashed border-rule px-6 py-10 text-center">
          <p className="text-ink/90">
            No leagues synced yet. If your Yahoo season hasn&apos;t started, this is
            expected — check back once your league is live.
          </p>
          <button
            type="button"
            onClick={handleManualSync}
            className="mt-5 border-2 border-ink bg-ink px-5 py-2.5 font-mono text-sm uppercase tracking-wide text-paper transition-colors hover:bg-paper hover:text-ink"
          >
            Sync again
          </button>
          <p className="mt-4">
            <a
              href="/"
              className="font-mono text-xs uppercase tracking-wide text-ink/70 underline decoration-rule underline-offset-4 hover:text-ink hover:decoration-ink"
            >
              Back to NineCat
            </a>
          </p>
        </div>
      )}

      {status === "picker" && (
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {leagues.map((league) => (
            <LeaguePickerCard key={league.id} league={league} />
          ))}
        </div>
      )}
    </main>
  );
}
