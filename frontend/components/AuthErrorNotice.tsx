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
    <div
      role="alert"
      className="flex items-start justify-between gap-4 border-l-4 border-alert bg-ink/[0.03] px-4 py-3"
    >
      <p className="text-sm text-ink">
        <strong className="font-semibold">Sign-in with Yahoo didn&apos;t go through.</strong>{" "}
        Try signing in again.
      </p>
      {/* 24x24 min hit area per WCAG 2.5.8 — the glyph itself stays small */}
      <button
        type="button"
        onClick={handleDismiss}
        aria-label="Dismiss"
        className="flex h-6 w-6 shrink-0 items-center justify-center font-mono text-sm text-ink/70 hover:text-ink"
      >
        ×
      </button>
    </div>
  );
}
