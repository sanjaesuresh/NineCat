"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";

// renders only when the OAuth callback redirected back with ?auth_error=1;
// dismissible locally (no need to round-trip the URL) and announced via
// role="alert" so screen reader users hear it without hunting for it.
export default function AuthErrorNotice({
  focusTargetId,
}: {
  // id of the control to return focus to on dismiss, so keyboard users
  // aren't dropped back to the top of the document
  focusTargetId: string;
}) {
  const searchParams = useSearchParams();
  const [dismissed, setDismissed] = useState(false);

  if (searchParams.get("auth_error") !== "1" || dismissed) {
    return null;
  }

  function handleDismiss() {
    setDismissed(true);
    document.getElementById(focusTargetId)?.focus();
  }

  return (
    // this notice only ever renders inside the hero's maroon panel (see
    // page.tsx), which doesn't flip with the site theme — so it uses the
    // fixed cream/espresso/foul trio instead of the theme-adaptive
    // paper/ink/alert tokens, which would go dark-on-dark in dark mode
    <div
      role="alert"
      className="flex items-start justify-between gap-4 border-2 border-foul bg-cream px-4 py-3"
    >
      <p className="text-sm text-espresso">
        {/* plain, unmistakable copy — no referee/whistle flavor here: a real
            error is the wrong place for decorative voice, it read as part of
            the message itself instead of a label */}
        <strong className="font-semibold">Sign-in with Yahoo didn&apos;t go through.</strong>{" "}
        Try signing in again.
      </p>
      {/* 24x24 min hit area per WCAG 2.5.8 — the glyph itself stays small */}
      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Dismiss"
        className="flex h-6 w-6 shrink-0 items-center justify-center font-mono text-sm text-espresso/70 hover:text-espresso"
      >
        ×
      </button>
    </div>
  );
}
