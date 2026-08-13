import Link from "next/link";
import type { League } from "@/lib/api";
import { formatSyncedAt } from "./format";

export default function LeaguePickerCard({ league }: { league: League }) {
  return (
    <Link
      href={`/dashboard/${league.id}`}
      className="block border border-ink px-5 py-4 no-underline transition-colors hover:bg-ink hover:text-paper"
    >
      <p className="font-mono text-xs uppercase tracking-wide opacity-70">{league.season}</p>
      <h2 className="mt-1 font-display text-xl">{league.name}</h2>
      <p className="mt-2 font-mono text-xs opacity-70">
        Last synced: {formatSyncedAt(league.synced_at)}
      </p>
    </Link>
  );
}
