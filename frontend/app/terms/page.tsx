import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms — NineCat",
  description: "The terms for using NineCat, a personal-use, advisory-only tool.",
};

export default function TermsPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-14 sm:px-10 sm:py-20">
      <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink/70">
        Effective August 11, 2026
      </p>
      <h1 className="mt-3 font-display text-4xl tracking-tight text-ink sm:text-5xl">
        Terms of Service
      </h1>
      <p className="mt-6 max-w-prose text-ink/90">
        By signing in to NineCat, you agree to the terms below.
      </p>

      <div className="mt-10 space-y-10">
        <section>
          <h2 className="font-display text-xl text-ink">
            What NineCat is
          </h2>
          <p className="mt-3 max-w-prose text-ink/90">
            NineCat is a personal-use tool for analyzing Yahoo Fantasy Basketball
            head-to-head, 9-category leagues. It is provided as-is, free of charge, and
            is not a commercial product.
          </p>
        </section>

        <section>
          <h2 className="font-display text-xl text-ink">
            Advisory only — no guaranteed results
          </h2>
          <p className="mt-3 max-w-prose text-ink/90">
            Everything NineCat shows you is a suggestion, not a promise. It does not
            guarantee any draft, matchup, waiver, or trade outcome, and is not
            responsible for the results of decisions you make using it.
          </p>
        </section>

        <section>
          <h2 className="font-display text-xl text-ink">
            Read-only access
          </h2>
          <p className="mt-3 max-w-prose text-ink/90">
            NineCat only reads data from your Yahoo Fantasy account. It never submits a
            draft pick, roster add or drop, or trade on your behalf — every move stays
            yours to make directly in Yahoo Fantasy.
          </p>
        </section>

        <section>
          <h2 className="font-display text-xl text-ink">
            Not affiliated with Yahoo or the NBA
          </h2>
          <p className="mt-3 max-w-prose text-ink/90">
            NineCat is an independent project. It is not affiliated with, endorsed by,
            or sponsored by Yahoo or the NBA. &quot;Yahoo Fantasy&quot; and related marks
            belong to their respective owners.
          </p>
        </section>

        <section>
          <h2 className="font-display text-xl text-ink">
            Termination and deletion
          </h2>
          <p className="mt-3 max-w-prose text-ink/90">
            You can stop using NineCat and delete your account at any time from
            Settings, which removes your stored data as described in the{" "}
            <a
              href="/privacy"
              className="underline decoration-rule underline-offset-4 hover:decoration-ink"
            >
              Privacy Policy
            </a>
            . We may also suspend or remove access for misuse of the service or of
            Yahoo&apos;s API.
          </p>
        </section>

        <section>
          <h2 className="font-display text-xl text-ink">
            Changes to these terms
          </h2>
          <p className="mt-3 max-w-prose text-ink/90">
            If these terms change, the effective date above will be updated. Continued
            use of NineCat after a change means you accept the updated terms.
          </p>
        </section>

        <section>
          <h2 className="font-display text-xl text-ink">Contact</h2>
          <p className="mt-3 max-w-prose text-ink/90">
            Questions about these terms:{" "}
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
