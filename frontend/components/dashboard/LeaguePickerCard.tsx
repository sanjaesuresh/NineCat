import Link from "next/link";
import type { League } from "@/lib/api";
import { formatSyncedAt } from "./format";
import { captionClasses, eyebrowClasses, headingClasses } from "@/components/dashboard/layout/typography";
import { controlMotionClasses } from "@/components/dashboard/layout/layoutTokens";

export default function LeaguePickerCard({ league }: { league: League }) {
  return (
    <Link
      href={`/dashboard/${league.id}`}
      className={`block border border-ink px-5 py-4 no-underline hover:bg-ink hover:text-paper ${controlMotionClasses()}`}
    >
      <p className={eyebrowClasses()}>{league.season}</p>
      <h2 className={`mt-1 ${headingClasses()}`}>{league.name}</h2>
      <p className={`mt-2 ${captionClasses()}`}>
        Last synced: {formatSyncedAt(league.synced_at)}
      </p>
    </Link>
  );
}
