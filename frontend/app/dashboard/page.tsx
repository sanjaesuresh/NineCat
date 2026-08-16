"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getMe, syncLeagues, isUnauthorized, ApiError, type League } from "@/lib/api";
import LeaguePickerCard from "@/components/dashboard/LeaguePickerCard";
import ErrorState from "@/components/dashboard/ErrorState";
import LogoutButton from "@/components/dashboard/LogoutButton";
import { SkeletonCard } from "@/components/dashboard/Skeletons";
import { captionClasses, controlClasses, proseClasses } from "@/components/dashboard/layout/typography";
import { controlMotionClasses } from "@/components/dashboard/layout/layoutTokens";

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

  // 0/1/many branching shared by the initial load and the manual "sync again"
  // action; returns true once resolved to a terminal (non-syncing) status.
  function settle(current: League[]): boolean {
    if (current.length === 1) {
      router.replace(`/dashboard/${current[0].id}`);
      return true;
    }
    if (current.length > 1) {
      setLeagues(current);
      setStatus("picker");
      return true;
    }
    return false;
  }

  async function resolve(current: League[]) {
    if (settle(current)) return;
    // zero leagues: try one automatic sync before showing the empty state —
    // covers the common case of a first-time sign-in that hasn't synced yet
    if (hasAutoSynced.current) {
      setStatus("empty");
      return;
    }
    hasAutoSynced.current = true;
    await runSync();
  }

  async function runSync() {
    setStatus("syncing");
    setErrorMessage(null);
    try {
      const synced = await syncLeagues();
      if (!settle(synced)) setStatus("empty");
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

  useEffect(() => {
    // standard fetch-on-mount: load() only sets the status that useState already
    // initializes it to; the retry path re-invokes the same function from a click handler
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load() only needs to run once on mount
  }, []);

  return (
    <main className="mx-auto min-w-0 w-full max-w-4xl px-6 py-14 sm:px-10 sm:py-20">
      <div className="flex items-baseline justify-between gap-4">
        <h1 className="font-display text-headline text-ink">Your leagues</h1>
        <LogoutButton />
      </div>

      {(status === "loading" || status === "syncing") && (
        <div className="mt-8 space-y-4" aria-busy="true">
          <p role="status" className="sr-only">
            {status === "syncing" ? "Syncing leagues…" : "Loading leagues…"}
          </p>
          <p className={captionClasses()} aria-hidden="true">
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
          <p className={proseClasses()}>
            No leagues synced yet. If your Yahoo season hasn&apos;t started, this is
            expected — check back once your league is live.
          </p>
          <button
            type="button"
            onClick={runSync}
            className={`mt-5 border-2 border-ink bg-ink px-5 py-2.5 font-condensed text-ui font-semibold text-paper hover:bg-paper hover:text-ink ${controlMotionClasses()}`}
          >
            Sync again
          </button>
          <p className="mt-4">
            <Link
              href="/"
              className={`underline decoration-rule underline-offset-4 hover:text-ink hover:decoration-ink ${controlClasses("muted")}`}
            >
              Back to NineCat
            </Link>
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
