// pulse blocks, never a spinner-on-white — matches the box-score idiom (a
// table shape you can recognize before the data lands) and respects
// prefers-reduced-motion via the global rule in globals.css.
import type { CSSProperties } from "react";

export function SkeletonLine({
  className = "",
  style,
}: {
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div className={`animate-pulse rounded-sm bg-ink/10 ${className}`} style={style} aria-hidden="true" />
  );
}

export function SkeletonTable({ rows = 4, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="border border-rule" aria-hidden="true">
      <div className="flex gap-2 border-b-2 border-ink px-3 py-2">
        {Array.from({ length: cols }).map((_, i) => (
          <SkeletonLine key={i} className="h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-2 border-b border-rule px-3 py-3 last:border-b-0">
          {Array.from({ length: cols }).map((_, c) => (
            <SkeletonLine key={c} className="h-3 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2 border border-rule p-4" aria-hidden="true">
      {Array.from({ length: lines }).map((_, i) => (
        <SkeletonLine key={i} className="h-3" style={{ width: `${85 - i * 15}%` }} />
      ))}
    </div>
  );
}
