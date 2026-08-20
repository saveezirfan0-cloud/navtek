"use client";

import type { Ingest } from "@/lib/api";

/** Downloads the rows currently on screen as CSV. Client-side because the
 * download is built in the browser; the rows come from the server-filtered
 * page, so what you see is exactly what you get. */

function csvField(value: unknown): string {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export default function CsvButton({ rows }: { rows: Ingest[] }) {
  const downloadCsv = () => {
    const header = ["order", "opportunity_id", "status", "notes", "when", "duration_s"];
    const lines = [header.join(",")].concat(
      rows.map((r) => [
        csvField(r.item_name ?? r.file_name ?? ""),
        csvField(r.opportunity_id ?? ""),
        csvField(r.status),
        csvField(r.error ?? [...(r.changed_fields ?? []), ...(r.warnings ?? [])].join(" | ")),
        csvField(r.created_at),
        csvField(r.duration_ms ? (r.duration_ms / 1000).toFixed(1) : ""),
      ].join(",")),
    );
    const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `navtek-eorder-reads-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <button className="act ghost" type="button" onClick={downloadCsv}
            disabled={rows.length === 0}>
      ⬇ CSV ({rows.length})
    </button>
  );
}
