import { Suspense } from "react";
import AuthErrorNotice from "@/components/AuthErrorNotice";
import CategoryLedger from "@/components/CategoryLedger";
import ToolRow from "@/components/ToolRow";

const TOOLS = [
  {
    stage: "01",
    name: "Draft Assistant",
    status: "Coming this draft season",
    description:
      "Live, pick-by-pick recommendations that fit the category build you're drafting toward.",
  },
  {
    stage: "02",
    name: "Matchup Monitor",
    status: "Coming soon",
    description:
      "A weekly read on your opponent's roster build and a projected category-by-category score before the matchup locks.",
  },
  {
    stage: "03",
    name: "Waiver Adds",
    status: "Coming soon",
    description:
      "Daily pickup suggestions that respect your league's add limits — no more, no less.",
  },
  {
    stage: "04",
    name: "Trade Analyzer",
    status: "Coming soon",
    description:
      "Two-sided trade suggestions that account for both rosters' category needs.",
  },
];

const HOW_IT_WORKS = [
  {
    step: "01",
    title: "Connect your Yahoo account",
    description: "One-time sign-in through Yahoo. Read-only from the first request.",
  },
  {
    step: "02",
    title: "We read your league",
    description:
      "Teams, rosters, and your league's exact 9-category scoring settings sync in.",
  },
  {
    step: "03",
    title: "You get advisory recommendations",
    description:
      "NineCat suggests; you decide. It never makes picks, adds, or trades for you.",
  },
];

export default function Home() {
  return (
    <main>
      {/* hero */}
      <section className="mx-auto max-w-4xl px-6 py-14 sm:px-10 sm:py-20">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink/70">
          Yahoo Fantasy Basketball — head-to-head, 9 categories
        </p>
        <h1 className="mt-3 font-display text-6xl font-bold tracking-tight text-ink sm:text-8xl">
          NineCat
        </h1>
        <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,1fr)_24rem] lg:items-start">
          <div>
            <p className="max-w-prose text-xl leading-relaxed text-ink/90">
              Reads your Yahoo head-to-head 9-category league and tells you what to do
              next —{" "}
              <em className="font-body italic">
                it never makes the moves for you
              </em>
              .
            </p>
            <div className="mt-8 flex flex-col items-start gap-4">
              {/* alert precedes the control it refers to, both visually and in DOM order */}
              <Suspense fallback={null}>
                <AuthErrorNotice focusTargetId="yahoo-signin-cta" />
              </Suspense>
              <a
                id="yahoo-signin-cta"
                href="/api/auth/yahoo/login"
                className="border-2 border-ink bg-ink px-6 py-3 font-mono text-sm uppercase tracking-wide text-paper transition-colors hover:bg-paper hover:text-ink"
              >
                Sign in with Yahoo
              </a>
            </div>
          </div>
          <CategoryLedger variant="full" />
        </div>
      </section>

      {/* what's shipping first */}
      <section className="border-t-2 border-ink bg-ink/[0.03]">
        <div className="mx-auto max-w-4xl px-6 py-8 sm:px-10">
          <div className="flex flex-wrap items-center gap-3">
            <span className="inline-flex items-center gap-2 border border-court px-2 py-1 font-mono text-[0.65rem] uppercase tracking-wide text-ink">
              <span className="h-1.5 w-1.5 rounded-full bg-court" aria-hidden="true" />
              First release
            </span>
            <h2 className="font-display text-lg font-semibold text-ink">
              The core pipeline
            </h2>
          </div>
          <p className="mt-3 max-w-prose text-ink/80">
            Sign in with Yahoo starts the pipeline — league sync and your team&apos;s
            9-category build breakdown are rolling out now, ahead of the four tools
            below.
          </p>
        </div>
      </section>

      {/* tools, in season order */}
      <section className="mx-auto max-w-4xl px-6 py-14 sm:px-10 sm:py-20">
        <h2 className="font-display text-3xl font-semibold text-ink">
          Four tools, in season order
        </h2>
        <div>
          {TOOLS.map((tool) => (
            <ToolRow key={tool.name} {...tool} />
          ))}
        </div>
      </section>

      {/* how it works */}
      <section className="border-t-2 border-ink">
        <div className="mx-auto max-w-4xl px-6 py-14 sm:px-10 sm:py-20">
          <h2 className="font-display text-3xl font-semibold text-ink">How it works</h2>
          <ol className="mt-8 grid gap-8 sm:grid-cols-3">
            {HOW_IT_WORKS.map((item) => (
              <li key={item.step} className="border-l-2 border-rule pl-4">
                <span className="font-mono text-sm text-ink/70">{item.step}</span>
                <h3 className="mt-1 font-display text-lg font-semibold text-ink">
                  {item.title}
                </h3>
                <p className="mt-1 text-ink/80">{item.description}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </main>
  );
}
