"use client";

import { useMemo, useState } from "react";
import type { Ingest } from "@/lib/api";

/** The recent-reads table, with the three things an operator reaches for:
 * find an order by name/ID, narrow to the ones needing attention, and get
 * the lot into a spreadsheet. All client-side over the rows already loaded. */

const PILL: Record<string, [string, string]> = {
  read: ["p-read", "Read"],
  check: ["p-check", "Check"],
  failed: ["p-failed", "Failed"],
};

function when(iso: string) {
  const d = new Date(iso);
  const thisYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleString("en-AU", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    ...(thisYear ? {} : { year: "numeric" }),
  });
}

function csvField(value: unknown): string {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export default function RecentTable({ rows }: { rows: Ingest[] }) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | "read" | "check" | "failed">("all");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((r) => {
      if (status !== "all" && r.status !== status) return false;
      if (!needle) return true;
      return [r.item_name, r.opportunity_id, r.file_name, r.error,
              ...(r.warnings ?? []), ...(r.changed_fields ?? [])]
        .some((v) => v && String(v).toLowerCase().includes(needle));
    });
  }, [rows, query, status]);

  const downloadCsv = () => {
    const header = ["order", "opportunity_id", "status", "notes", "when", "duration_s"];
    const lines = [header.join(",")].concat(
      filtered.map((r) => [
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
    <>
      <div className="table-tools">
        <input
          className="field"
          style={{ marginBottom: 0, maxWidth: 260 }}
          placeholder="Search order, ID, note…"
          aria-label="Search recent reads"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="chips" role="group" aria-label="Filter by status">
          {(["all", "read", "check", "failed"] as const).map((s) => (
            <button
              key={s}
              type="button"
              className={`chip-btn ${status === s ? "on" : ""}`}
              onClick={() => setStatus(s)}
            >
              {s === "all" ? "All" : PILL[s][1]}
            </button>
          ))}
        </div>
        <button className="act ghost" type="button" onClick={downloadCsv}
                disabled={filtered.length === 0}>
          ⬇ CSV ({filtered.length})
        </button>
      </div>

      {filtered.length === 0 ? (
        <p className="empty">Nothing matches that filter.</p>
      ) : (
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th>Order</th>
                <th>Status</th>
                <th>Notes</th>
                <th>When</th>
                <th>Took</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => {
                const [cls, label] = PILL[r.status] ?? ["p-check", r.status];
                return (
                  <tr key={i}>
                    <td>
                      <div style={{ fontWeight: 600 }}>
                        {r.item_name ?? r.file_name ?? "—"}
                      </div>
                      {r.opportunity_id && (
                        <div className="mono" style={{ color: "var(--mid)" }}>
                          {r.opportunity_id}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className={`pill ${cls}`}>{label}</span>
                    </td>
                    <td style={{ color: "var(--mid)" }}>
                      {r.error ??
                        [...r.changed_fields, ...r.warnings].slice(0, 3).join(" · ") ??
                        ""}
                    </td>
                    <td className="num">{when(r.created_at)}</td>
                    <td className="num">
                      {r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
