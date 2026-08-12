import { classifyInjury } from "./format";

// same pill shape as the landing page's "coming soon" status (border + dot +
// full-contrast ink text) so accent color never carries meaning on its own.
const TONE_BORDER: Record<"alert" | "amber", string> = {
  alert: "border-alert",
  amber: "border-amber",
};
const TONE_DOT: Record<"alert" | "amber", string> = {
  alert: "bg-alert",
  amber: "bg-amber",
};

export default function InjuryBadge({ status }: { status: string | null }) {
  const injury = classifyInjury(status);
  if (!injury) return null;

  return (
    <span
      className={`inline-flex w-fit items-center gap-1.5 border px-1.5 py-0.5 font-mono text-[0.65rem] uppercase tracking-wide text-ink ${TONE_BORDER[injury.tone]}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOT[injury.tone]}`} aria-hidden="true" />
      {injury.label}
    </span>
  );
}
