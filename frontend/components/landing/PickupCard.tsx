"use client";

// only this leaf needs "use client": onError handling for the remote NBA
// headshot requires a client-side event handler, everything else here is static markup.
import { useState } from "react";
import Image from "next/image";
import PlayerChip from "./PlayerChip";

export interface PickupCardProps {
  /** NBA.com person id used to build the cdn.nba.com headshot URL. */
  personId: string;
  name: string;
  /** two-letter fallback shown inside PlayerChip when the headshot fails to load. */
  initials: string;
  /** full "POS · TEAM — stat line" proof string, copied verbatim from the mockup. */
  meta: string;
  /** category-fix tags, e.g. ["+ Ast", "+ Ft%"]. */
  fixes: readonly string[];
}

export default function PickupCard({ personId, name, initials, meta, fixes }: PickupCardProps) {
  const [imageFailed, setImageFailed] = useState(false);

  return (
    <div className="flex items-center gap-3 border border-rule bg-paper-2 px-3 py-2.5">
      {imageFailed ? (
        // fixed footprint matches the headshot's box so the fallback doesn't reflow the card
        <div
          className="flex h-12 w-[66px] shrink-0 items-center justify-center border border-rule bg-ink-fill"
          role="img"
          aria-label={`${name} headshot unavailable`}
        >
          <PlayerChip jersey={initials} color="var(--blue-txt)" />
        </div>
      ) : (
        <Image
          src={`https://cdn.nba.com/headshots/nba/latest/260x190/${personId}.png`}
          alt={`${name} headshot`}
          width={66}
          height={48}
          className="h-12 w-[66px] shrink-0 border border-rule bg-ink-fill object-cover [filter:saturate(.85)_contrast(1.05)]"
          onError={() => setImageFailed(true)}
        />
      )}
      <div>
        <span className="block font-condensed text-[15px] font-bold text-ink">{name}</span>
        <span className="mt-0.5 block font-condensed text-[11.5px] font-semibold text-ink-muted">
          {meta}
        </span>
        <span className="mt-[5px] flex flex-wrap gap-[5px]">
          {fixes.map((fix) => (
            <span
              key={fix}
              className="border border-blue-txt px-[7px] py-[2px] font-condensed text-[10.5px] font-extrabold tracking-[0.08em] text-blue-txt uppercase"
            >
              {fix}
            </span>
          ))}
        </span>
      </div>
    </div>
  );
}
