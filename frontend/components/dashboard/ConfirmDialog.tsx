"use client";

import { useRef, useState } from "react";
import { ApiError } from "@/lib/api";

/**
 * Accessible confirm dialog built on native <dialog> — showModal() gives us
 * focus containment and Escape-to-close for free, so no custom focus-trap
 * code is needed. Optionally requires typing an exact phrase before the
 * confirm action becomes available (used for account deletion).
 */
export default function ConfirmDialog({
  triggerLabel,
  triggerClassName,
  title,
  description,
  confirmLabel,
  pendingLabel = "Working…",
  requirePhrase,
  danger = false,
  onConfirm,
}: {
  triggerLabel: string;
  triggerClassName: string;
  title: string;
  description: string;
  confirmLabel: string;
  pendingLabel?: string;
  requirePhrase?: string;
  danger?: boolean;
  onConfirm: () => Promise<void>;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [typedPhrase, setTypedPhrase] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function open() {
    setError(null);
    setTypedPhrase("");
    dialogRef.current?.showModal();
  }

  function close() {
    if (pending) return; // don't let a stray Escape abandon an in-flight request
    dialogRef.current?.close();
  }

  async function handleConfirm() {
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      // caller navigates away on success (redirect to "/"); nothing left to reset here
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `That didn't go through (${err.status}). Try again.`
          : "That didn't go through. Check your connection and try again.",
      );
      setPending(false);
    }
  }

  const phraseSatisfied = !requirePhrase || typedPhrase === requirePhrase;

  return (
    <>
      <button type="button" onClick={open} className={triggerClassName}>
        {triggerLabel}
      </button>
      <dialog
        ref={dialogRef}
        onCancel={(e) => {
          if (pending) e.preventDefault();
        }}
        onClick={(e) => {
          if (e.target === dialogRef.current) close();
        }}
        className="w-full max-w-md border-2 border-ink bg-paper p-6 text-ink backdrop:bg-ink/40"
        aria-labelledby="confirm-dialog-title"
      >
        <h2 id="confirm-dialog-title" className="font-display text-lg font-semibold text-ink">
          {title}
        </h2>
        <p className="mt-2 text-sm text-ink/90">{description}</p>

        {requirePhrase && (
          <label className="mt-4 block">
            <span className="font-mono text-xs uppercase tracking-wide text-ink/70">
              Type {requirePhrase} to confirm
            </span>
            <input
              type="text"
              value={typedPhrase}
              onChange={(e) => setTypedPhrase(e.target.value)}
              autoComplete="off"
              className="mt-1 w-full border border-ink bg-paper px-3 py-2 font-mono text-sm text-ink"
            />
          </label>
        )}

        {error && (
          <p role="alert" className="mt-3 border-l-4 border-alert bg-ink/[0.03] px-3 py-2 text-sm text-ink">
            {error}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-3">
          <button
            type="button"
            onClick={close}
            disabled={pending}
            className="border border-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wide text-ink hover:bg-ink hover:text-paper disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={pending || !phraseSatisfied}
            className={`border px-3 py-1.5 font-mono text-xs uppercase tracking-wide transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
              danger
                ? "border-alert text-ink hover:bg-alert hover:text-paper"
                : "border-ink text-ink hover:bg-ink hover:text-paper"
            }`}
          >
            {pending ? pendingLabel : confirmLabel}
          </button>
        </div>
      </dialog>
    </>
  );
}
