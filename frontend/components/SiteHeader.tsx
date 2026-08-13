import Link from "next/link";
import MastheadNav from "./MastheadNav";
import { SOURCE_SEASON } from "@/lib/hashtagPool";

// dateline + masthead — deliberately has no h1 of its own, so every page
// keeps a single h1 in its own <main>. shows on every route (home, privacy,
// terms, dashboard). matches the approved d-retrodata mockup's two-tier
// newspaper masthead: dateline strip, wordmark row, thick+tricolor rules.
// this stays a server component; the landing-only anchor nav is split out
// into the client component MastheadNav so this file never needs "use client".
export default function SiteHeader() {
  return (
    <header>
      {/* dateline strip: print-edition flavor line, purely decorative framing */}
      <div className="bg-ink-fill py-[7px] font-condensed text-[11.5px] font-bold uppercase tracking-[0.12em] text-cream">
        <div className="mx-auto flex max-w-6xl flex-wrap justify-between gap-2 px-6 sm:px-10">
          {/* reuses the same SOURCE_SEASON constant as the footer's fine
              print so the two season strings can't drift out of sync */}
          <span>Vol. I · No. 41 · {SOURCE_SEASON} Season</span>
          <span className="text-gold">Yahoo H2H 9‑Cat Edition</span>
        </div>
      </div>

      <div className="bg-paper pt-4">
        <div className="mx-auto flex max-w-6xl flex-wrap items-end justify-between gap-x-6 gap-y-4 px-6 pb-3.5 sm:px-10">
          <div className="flex items-baseline gap-2.5">
            <Link
              href="/"
              className="font-display text-[clamp(34px,4vw,52px)] leading-none uppercase tracking-[0.01em] text-ink no-underline transition-opacity hover:opacity-80 focus-visible:opacity-80"
            >
              NINE<span className="text-red-ink">CAT</span>
            </Link>
            <span className="self-center border-l-2 border-ink pl-2.5 font-condensed text-xs font-bold uppercase tracking-[0.2em] text-ink">
              The 9‑Cat Daily
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-[26px]">
            {/* mockup hides the anchor nav below 700px; the sign-in button
                sits outside this element so it stays reachable at every width.
                MastheadNav renders nothing off the landing route ("/"). */}
            <MastheadNav />
            <a
              href="/api/auth/yahoo/login"
              className="inline-flex items-center gap-2 whitespace-nowrap border-2 border-ink bg-ink-fill px-[18px] py-[11px] font-condensed text-sm font-extrabold uppercase tracking-[0.05em] text-cream no-underline transition-colors hover:border-alert-fill hover:bg-alert-fill"
            >
              {/* border matches the hover background so the button reads as one
                  solid color block, not a hairline against paper — bg-alert-fill
                  and border-alert-fill are the same color here, never separately
                  legible as a thin line */}
              <span
                className="h-[9px] w-[9px] rounded-full bg-[#6001D2]"
                aria-hidden="true"
              />
              Sign in with Yahoo
            </a>
          </div>
        </div>

        {/* thick rule + tricolor thin-rule band: decorative masthead dressing,
            not informational, so hidden from assistive tech */}
        <div className="h-1.5 bg-ink" aria-hidden="true" />
        <div className="flex h-1" aria-hidden="true">
          <span className="flex-1 bg-alert-fill" />
          <span className="flex-1 border-x-[3px] border-ink bg-paper" />
          <span className="flex-1 bg-court-fill" />
        </div>
      </div>
    </header>
  );
}
