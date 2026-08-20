"use client";

import { useEffect } from "react";

/** Transient confirmation that an action landed. The admin pages used to act
 * silently on success — a flipped switch that quietly saved looked identical
 * to one that quietly didn't. Auto-dismisses; errors stay until replaced. */
export default function Toast({
  message,
  error = false,
  onDone,
}: {
  message: string;
  error?: boolean;
  onDone: () => void;
}) {
  useEffect(() => {
    if (error) return; // errors don't time out — they need to be read
    const id = setTimeout(onDone, 3500);
    return () => clearTimeout(id);
  }, [message, error, onDone]);

  return (
    <div className={`toast ${error ? "err" : ""}`} role="status" aria-live="polite">
      {message}
    </div>
  );
}
