"use client";

import { useState } from "react";
import type { DayStat } from "@/lib/api";

/**
 * The last 30 days of reads as one stacked bar per day, coloured by the
 * app's own status tokens (read → green, check → amber, failed → red).
 *
 * Status colours are semantically fixed app-wide, and red↔amber is a weak
 * pair under deuteranopia — so identity is never colour alone here: the
 * stack order is fixed (read at the baseline, failed on top), failed
 * segments carry a 45° hatch, every segment is separated by a surface-
 * coloured ring, the legend names each band, and hovering a day lists its
 * exact counts.
 */

const W = 960;
const H = 190;
const PAD_L = 34;
const PAD_R = 8;
const PAD_T = 10;
const PAD_B = 26;

const SERIES = [
  { key: "read", label: "Read cleanly", color: "var(--green)" },
  { key: "check", label: "Need a look", color: "var(--amber)" },
  { key: "failed", label: "Failed", color: "var(--red)" },
] as const;

function niceMax(value: number): number {
  if (value <= 5) return Math.max(1, value);
  const pow = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 5, 10]) {
    if (value <= step * pow) return step * pow;
  }
  return 10 * pow;
}

function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

export default function ActivityChart({ days }: { days: DayStat[] }) {
  const [hover, setHover] = useState<number | null>(null);

  const total = days.reduce((n, d) => n + d.read + d.check + d.failed, 0);
  const yMax = niceMax(Math.max(1, ...days.map((d) => d.read + d.check + d.failed)));
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;
  const slot = plotW / days.length;
  const barW = Math.min(22, slot * 0.62);
  const y = (v: number) => PAD_T + plotH - (v / yMax) * plotH;

  const hovered = hover === null ? null : days[hover];

  return (
    <div className="chart-wrap">
      <div className="chart-legend" aria-hidden="true">
        {SERIES.map((s) => (
          <span className="chart-key" key={s.key}>
            <i
              className={s.key === "failed" ? "hatched" : ""}
              style={{ background: s.key === "failed" ? undefined : s.color }}
            />
            {s.label}
          </span>
        ))}
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="chart"
        role="img"
        aria-label={`Daily eOrder reads over the last ${days.length} days: ${total} in total.`}
      >
        <defs>
          {/* The CVD/print fallback for the failed band: red alone is not
              relied on to say "failed". */}
          <pattern id="fail-hatch" width="5" height="5" patternUnits="userSpaceOnUse"
                   patternTransform="rotate(45)">
            <rect width="5" height="5" fill="var(--red)" />
            <line x1="0" y1="0" x2="0" y2="5" stroke="var(--card)"
                  strokeWidth="1.6" opacity="0.55" />
          </pattern>
        </defs>

        {/* Recessive grid: baseline, midpoint, top. */}
        {[0, yMax / 2, yMax].map((v) => (
          <g key={v}>
            <line x1={PAD_L} x2={W - PAD_R} y1={y(v)} y2={y(v)}
                  stroke="var(--line-soft)" strokeWidth="1" />
            <text x={PAD_L - 6} y={y(v) + 3.5} textAnchor="end" className="chart-tick">
              {Number.isInteger(v) ? v : v.toFixed(1)}
            </text>
          </g>
        ))}

        {days.map((d, i) => {
          const cx = PAD_L + slot * i + slot / 2;
          const x = cx - barW / 2;
          const dayTotal = d.read + d.check + d.failed;
          let cursor = 0;
          const segments = SERIES.map((s) => {
            const value = d[s.key];
            const y0 = y(cursor + value);
            const h = y(cursor) - y0;
            cursor += value;
            return { ...s, value, y0, h };
          }).filter((s) => s.value > 0);
          const top = segments[segments.length - 1];

          return (
            <g key={d.date}>
              {segments.map((s) => {
                const fill = s.key === "failed" ? "url(#fail-hatch)" : s.color;
                if (s === top) {
                  // The data-end: rounded top corners, anchored square at
                  // the stack below.
                  const r = Math.min(3, s.h, barW / 2);
                  return (
                    <path
                      key={s.key}
                      d={`M${x},${s.y0 + s.h} V${s.y0 + r} Q${x},${s.y0} ${x + r},${s.y0} H${x + barW - r} Q${x + barW},${s.y0} ${x + barW},${s.y0 + r} V${s.y0 + s.h} Z`}
                      fill={fill} stroke="var(--card)" strokeWidth="1"
                    />
                  );
                }
                return (
                  <rect key={s.key} x={x} y={s.y0} width={barW} height={s.h}
                        fill={fill} stroke="var(--card)" strokeWidth="1" />
                );
              })}
              {i === hover && dayTotal > 0 && (
                <line x1={cx} x2={cx} y1={PAD_T} y2={y(0)}
                      stroke="var(--line)" strokeWidth="1" strokeDasharray="3 3" />
              )}
              {/* The hit target — the whole day's column, not the thin bar. */}
              <rect x={PAD_L + slot * i} y={PAD_T} width={slot} height={plotH}
                    fill="transparent"
                    onMouseEnter={() => setHover(i)}
                    onMouseLeave={() => setHover(null)}>
                <title>{`${dayLabel(d.date)} — ${d.read} read, ${d.check} check, ${d.failed} failed`}</title>
              </rect>
              {(i % 5 === 0 || i === days.length - 1) && (
                <text x={cx} y={H - 8} textAnchor="middle" className="chart-tick">
                  {dayLabel(d.date)}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {hovered && (
        <div
          className="chart-tip"
          style={{ left: `${((PAD_L + slot * hover! + slot / 2) / W) * 100}%` }}
        >
          <div className="tip-when">{dayLabel(hovered.date)}</div>
          {SERIES.map((s) => (
            <div className="tip-row" key={s.key}>
              <i className={s.key === "failed" ? "hatched" : ""}
                 style={{ background: s.key === "failed" ? undefined : s.color }} />
              <span>{s.label}</span>
              <b>{hovered[s.key]}</b>
            </div>
          ))}
        </div>
      )}

      {total === 0 && (
        <p className="tiny" style={{ marginTop: 6 }}>
          Nothing read in this window yet — the chart fills in as eOrders arrive.
        </p>
      )}
    </div>
  );
}
