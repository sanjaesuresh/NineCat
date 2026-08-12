import Link from "next/link";

// masthead — deliberately has no h1 of its own, so every page keeps a single
// h1 in its own <main>. shows on every route (home, privacy, terms).
export default function SiteHeader() {
  return (
    <header className="border-b-2 border-ink">
      <div className="mx-auto flex max-w-4xl flex-wrap items-baseline justify-between gap-x-6 gap-y-2 px-6 py-5 sm:px-10">
        <Link
          href="/"
          className="font-display text-2xl font-bold tracking-tight text-ink no-underline"
        >
          NineCat
        </Link>
        <p className="order-3 w-full font-mono text-[0.65rem] uppercase tracking-[0.2em] text-ink/70 sm:order-none sm:w-auto">
          9-cat copilot for Yahoo Fantasy Basketball
        </p>
        <a
          href="/api/auth/yahoo/login"
          className="font-mono text-xs uppercase tracking-wide text-ink underline decoration-rule underline-offset-4 hover:decoration-ink"
        >
          Sign in with Yahoo
        </a>
      </div>
    </header>
  );
}
