import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy — NineCat",
  description: "What NineCat stores, what it never does, and how to delete your data.",
};

export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-14 sm:px-10 sm:py-20">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink/70">
        Effective August 11, 2026
      </p>
      <h1 className="mt-3 font-display text-4xl font-bold tracking-tight text-ink sm:text-5xl">
        Privacy Policy
      </h1>
      <p className="mt-6 max-w-prose text-ink/90">
        NineCat is a personal-use tool for analyzing your Yahoo Fantasy Basketball
        head-to-head league. This page explains what it stores about you, what it
        deliberately never does, and how to remove your data.
      </p>

      <div className="mt-10 space-y-10">
        <section>
          <h2 className="font-display text-xl font-semibold text-ink">What we store</h2>
          <ul className="mt-3 space-y-2 border-l-2 border-rule pl-4 text-ink/90">
            <li>Your Yahoo account ID, so we know which account is signed in.</li>
            <li>
              League, team, and roster data synced from Yahoo Fantasy — the same
              information visible in your Yahoo Fantasy app.
            </li>
            <li>
              Your Yahoo OAuth tokens, encrypted at rest, used only to make read
              requests to Yahoo&apos;s API on your behalf.
            </li>
          </ul>
        </section>

        <section>
          <h2 className="font-display text-xl font-semibold text-ink">
            What we never do
          </h2>
          <ul className="mt-3 space-y-2 border-l-2 border-rule pl-4 text-ink/90">
            <li>
              We never write anything back to Yahoo. NineCat cannot submit a draft
              pick, add, drop, or trade on your behalf — it only reads.
            </li>
            <li>We never sell or share your data with third parties.</li>
            <li>We run no third-party advertising or ad-tracking on this site.</li>
          </ul>
        </section>

        <section>
          <h2 className="font-display text-xl font-semibold text-ink">Cookies</h2>
          <p className="mt-3 max-w-prose text-ink/90">
            NineCat sets one session cookie to keep you signed in. There are no
            third-party analytics or advertising cookies.
          </p>
        </section>

        <section>
          <h2 className="font-display text-xl font-semibold text-ink">
            Deleting your data
          </h2>
          <p className="mt-3 max-w-prose text-ink/90">
            Today, email{" "}
            <a
              href="mailto:sanjaesuresh.school@gmail.com"
              className="underline decoration-rule underline-offset-4 hover:decoration-ink"
            >
              sanjaesuresh.school@gmail.com
            </a>{" "}
            and your stored league data and OAuth tokens will be removed. This cannot
            be undone. A self-serve Delete Account control is coming with the
            dashboard&apos;s settings page.
          </p>
        </section>

        <section>
          <h2 className="font-display text-xl font-semibold text-ink">
            Changes to this policy
          </h2>
          <p className="mt-3 max-w-prose text-ink/90">
            If this policy changes, the effective date above will be updated. Material
            changes will be noted on this page.
          </p>
        </section>

        <section>
          <h2 className="font-display text-xl font-semibold text-ink">Contact</h2>
          <p className="mt-3 max-w-prose text-ink/90">
            Questions about this policy or your data:{" "}
            <a
              href="mailto:sanjaesuresh.school@gmail.com"
              className="underline decoration-rule underline-offset-4 hover:decoration-ink"
            >
              sanjaesuresh.school@gmail.com
            </a>
            .
          </p>
        </section>
      </div>
    </main>
  );
}
