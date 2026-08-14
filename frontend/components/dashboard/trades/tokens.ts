// Structured-token translation for the Trades page. Same discipline as
// components/dashboard/matchup/tokens.ts and adds/tokens.ts: the engine emits
// contract keys only (see backend/src/ninecat/engine/trade_eval.py's REASON
// TOKEN VOCABULARY block), and every fixed token is typed as an explicit union
// so a token added on the backend without a translation here is a TypeScript
// compile error rather than a raw key reaching the screen. That bug class has
// shipped twice in this project and been caught in design review both times.
import { LABEL_BY_CONTRACT_KEY } from "@/components/dashboard/categoryKeys";

// TradeVerdict.verdict -- trade_eval.py's four values, from MY perspective.
export const VERDICT_TOKENS = ["favors_me", "favors_them", "balanced", "rejected"] as const;
export type VerdictToken = (typeof VERDICT_TOKENS)[number];

export function isVerdictToken(token: string): token is VerdictToken {
  return (VERDICT_TOKENS as readonly string[]).includes(token);
}

// TradeVerdict.reasons' two non-category tokens. The three category-prefixed
// families ("gained:" / "lost:" / "collapsed:") are handled generically below
// since there is one per CATEGORIES key.
export const STATIC_REASON_TOKENS = ["no_downside", "rejected"] as const;
type StaticReasonToken = (typeof STATIC_REASON_TOKENS)[number];

const STATIC_REASON_LABEL: Record<StaticReasonToken, string> = {
  no_downside: "Nothing on your roster gets materially worse",
  rejected:
    "Not worth doing — this collapses a category you're currently strong in, whatever the net value says",
};

function isStaticReasonToken(token: string): token is StaticReasonToken {
  return (STATIC_REASON_TOKENS as readonly string[]).includes(token);
}

// the three category-prefixed families, each with its own framing -- "lost"
// and "collapsed" are NOT the same severity and must not read the same way
const CATEGORY_PREFIX_LABEL = {
  "gained:": (label: string) => `Gains ${label}`,
  "lost:": (label: string) => `Gives up ground in ${label}`,
  "collapsed:": (label: string) => `Collapses ${label} — it stops being a strength`,
} as const;

/**
 * One TradeVerdict.reasons token. An unrecognized token surfaces as a visible
 * gap, never humanized into prose that looks intentional.
 */
export function describeReason(token: string): string {
  for (const [prefix, format] of Object.entries(CATEGORY_PREFIX_LABEL)) {
    if (!token.startsWith(prefix)) continue;
    const key = token.slice(prefix.length);
    const label = LABEL_BY_CONTRACT_KEY[key];
    // an unknown category key is still a gap, even inside a known prefix
    return label ? format(label) : `Unrecognized category (${key})`;
  }
  if (isStaticReasonToken(token)) return STATIC_REASON_LABEL[token];
  return `Unrecognized reason (${token}) — this note needs a translation.`;
}
