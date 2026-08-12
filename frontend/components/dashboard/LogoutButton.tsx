"use client";

import { useState } from "react";

/**
 * Logout intentionally bypasses lib/api.ts (per spec: plain fetch, not the
 * typed client) and always lands on "/" — even if the POST fails, the user's
 * intent was to leave the dashboard, so we never strand them mid-logout.
 */
export default function LogoutButton({ className }: { className?: string }) {
  const [pending, setPending] = useState(false);

  async function handleLogout() {
    setPending(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      // ignore — redirect happens regardless, see comment above
    } finally {
      window.location.href = "/";
    }
  }

  return (
    <button
      type="button"
      onClick={handleLogout}
      disabled={pending}
      className={
        className ??
        "font-mono text-xs uppercase tracking-wide text-ink underline decoration-rule underline-offset-4 hover:decoration-ink disabled:opacity-60"
      }
    >
      {pending ? "Signing out…" : "Log out"}
    </button>
  );
}
