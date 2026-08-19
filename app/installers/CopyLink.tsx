"use client";

import { useState } from "react";

/** Copies the full magic link. Client side so it reads the real origin — and
 * so an admin can hand a link over without OPENING it, which records a
 * 'viewed' audit event as though the installer had looked. */
export default function CopyLink({ token }: { token: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="act ghost"
      type="button"
      onClick={() => {
        navigator.clipboard.writeText(`${location.origin}/j/${token}`);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
    >
      {copied ? "Copied ✓" : "Copy link"}
    </button>
  );
}
