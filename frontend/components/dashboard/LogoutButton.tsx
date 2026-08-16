"use client";

import { useState } from "react";
import { controlClasses } from "@/components/dashboard/layout/typography";

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
      // hard navigation is deliberate here too — see settings page comment
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
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
        // inline-flex + py-1.5 pads the hit area to a ~24px target (WCAG 2.2 2.5.8)
        `inline-flex items-center py-1.5 underline decoration-rule underline-offset-4 hover:decoration-ink disabled:opacity-60 ${controlClasses()}`
      }
    >
      {pending ? "Signing out…" : "Log out"}
    </button>
  );
}
