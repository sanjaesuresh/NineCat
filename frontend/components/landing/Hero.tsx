import { Suspense } from "react";
import AuthErrorNotice from "@/components/AuthErrorNotice";
import PuntBuilder from "@/components/landing/PuntBuilder";

// hero + centerpiece — matches the approved d-retrodata mockup's .hero /
// .hero-top / .centerpiece rules. Server component: only the punt builder
// inside the centerpiece needs interactivity, so "use client" stays scoped
// to that leaf and the hero band itself ships zero client JS.
export default function Hero() {
  return (
    <section aria-labelledby="hero-heading" className="border-b-[6px] border-ink bg-alert-fill text-cream">
      {/* hero-top: halftone dot texture + solid corner color-block, both pure
          CSS (no image asset) so neither can cause layout shift or widen the
          page — same technique as the header/old-hero's .court-arcs pattern */}
      <div className="relative isolate overflow-hidden pb-11 pt-14 sm:pt-16">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 -z-10 opacity-[0.09]"
          style={{
            // color-mix keeps this on the --cream token (was a hardcoded rgba
            // duplicating cream's hex) instead of a second source of truth for the color
            backgroundImage:
              "radial-gradient(circle, color-mix(in srgb, var(--cream) 70%, transparent) 1.4px, transparent 1.6px)",
            backgroundSize: "10px 10px",
          }}
        />
        {/* solid corner block for team-color blocking; clip-path only, no gradient/blur */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -top-5 right-0 bottom-0 -z-10 w-[min(260px,24vw)] bg-court-fill"
          style={{ clipPath: "polygon(100% 0, 100% 100%, 46% 100%)" }}
        />

        <div className="relative mx-auto max-w-6xl px-6 sm:px-10">
          <span className="mb-5 inline-block bg-ink-fill px-3 py-1.5 font-condensed text-sm font-extrabold tracking-[0.14em] text-gold uppercase">
            Special 9-Cat Edition
          </span>
          <h1
            id="hero-heading"
            className="max-w-[17ch] font-display text-[clamp(40px,5.4vw,82px)] leading-[0.94] text-cream uppercase"
          >
            {/* gold-on-red (--gold on --alert-fill) is only 2.94:1 — fails both the
                3:1 large-text and 4.5:1 normal-text thresholds (design review C1).
                text-cream + a gold underline keeps the accent without breaking the
                headline/paragraph's inline flow the way the kicker's boxed
                treatment would; cream on --alert-fill measures 5.96:1. */}
            Every Category,{" "}
            <em className="text-cream underline decoration-gold decoration-2 underline-offset-4 not-italic">
              Graded
            </em>{" "}
            Like a Box Score.
          </h1>
          <p className="mt-[22px] max-w-[56ch] text-lg leading-[1.55] text-cream">
            NineCat reads your{" "}
            <strong className="text-cream underline decoration-gold decoration-2 underline-offset-4">
              Yahoo 9-cat league
            </strong>{" "}
            the way a stats page reads a box score — draft boards, matchup lines, and waiver
            targets built for people who already know the NBA and just want the edge the
            sheet gives them.
          </p>

          <div className="mt-[30px] flex flex-col items-start gap-4">
            {/* alert precedes the control it refers to, both visually and in DOM order */}
            <Suspense fallback={null}>
              <AuthErrorNotice focusTargetId="yahoo-signin-cta" />
            </Suspense>
            <div className="flex flex-wrap gap-4">
              {/* the global gold focus ring is only 2.94:1 on this red band (fails
                  the 3:1 UI-indicator threshold) and visually competes with the
                  ghost CTA's own cream border — scope both CTAs to a cream ring
                  instead (5.96:1 here), important so it beats the unlayered
                  global `:focus-visible` rule in globals.css */}
              <a
                id="yahoo-signin-cta"
                href="/api/auth/yahoo/login"
                className="border-2 border-ink-fill bg-cream px-[26px] py-[15px] font-condensed text-[17px] font-extrabold tracking-[0.05em] text-ink-fill uppercase transition-colors duration-150 ease-[var(--ease-out-quart)] hover:bg-gold focus-visible:outline-cream!"
              >
                Sign in with Yahoo
              </a>
              <a
                href="#build"
                className="border-2 border-cream px-[26px] py-[15px] font-condensed text-[17px] font-extrabold tracking-[0.05em] text-cream uppercase transition-colors duration-150 ease-[var(--ease-out-quart)] hover:bg-cream hover:text-ink-fill focus-visible:outline-cream!"
              >
                Build your punt draft ↓
              </a>
            </div>
          </div>
        </div>
      </div>

      {/* centerpiece: league-leaders build table driven by the punt picker.
          id lives on the panel (not PuntBuilder's inner div) so the ghost
          CTA's #build jump lands at the panel's top rule, not below it */}
      <div id="build" className="mt-11 border-t-[5px] border-ink bg-panel text-ink">
        <div className="mx-auto max-w-6xl px-6 sm:px-10">
          <PuntBuilder />
        </div>
      </div>
    </section>
  );
}
