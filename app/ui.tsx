import Link from "next/link";

/** Shared table furniture. Server components — the pager is links, not
 * state, so filters and pages survive a refresh and are shareable URLs. */

const PILL: Record<string, string> = {
  // ingest statuses
  read: "p-read",
  check: "p-check",
  failed: "p-failed",
  // webhook outcomes
  processed: "p-read",
  skipped: "p-check",
  // SLA states
  on_track: "p-read",
  due_now: "p-check",
  breached: "p-failed",
};

const PILL_LABEL: Record<string, string> = {
  read: "Read",
  check: "Check",
  failed: "Failed",
  processed: "Processed",
  skipped: "Skipped",
  on_track: "On track",
  due_now: "Due now",
  breached: "Breached",
};

export function Pill({ kind, label }: { kind: string; label?: string }) {
  return (
    <span className={`pill ${PILL[kind] ?? "p-check"}`}>
      {label ?? PILL_LABEL[kind] ?? kind}
    </span>
  );
}

/** Newest-first tables page with Newer/Older, not Prev/Next — the reader is
 * moving through time, and saying so beats making them work it out. */
export function Pager({
  page,
  pages,
  total,
  unit,
  hrefFor,
}: {
  page: number;
  pages: number;
  total: number;
  unit: string;
  hrefFor: (page: number) => string;
}) {
  if (pages <= 1) return null;
  return (
    <nav className="pager" aria-label={`${unit} pages`}>
      {page > 1 ? (
        <Link className="page-btn" href={hrefFor(page - 1)}>← Newer</Link>
      ) : (
        <span className="page-btn off">← Newer</span>
      )}
      <span className="page-where">
        Page {page} of {pages} · {total} {unit}
      </span>
      {page < pages ? (
        <Link className="page-btn" href={hrefFor(page + 1)}>Older →</Link>
      ) : (
        <span className="page-btn off">Older →</span>
      )}
    </nav>
  );
}

/** Clamp a ?page= search param to a sane 1-based page number. */
export function pageParam(raw: string | undefined): number {
  return Math.max(1, Number.parseInt(raw ?? "1", 10) || 1);
}
