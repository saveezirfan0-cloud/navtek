"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { Job } from "@/lib/api";
import { submit } from "./actions";

export default function JobActions({ job, token }: { job: Job; token: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [fitted, setFitted] = useState(String(job.units_installed || ""));

  const run = (
    action: "contacted" | "booked" | "progress" | "completed" | "blocked",
    value?: string | number,
  ) =>
    start(async () => {
      setError(null);
      const result = await submit({ token, item_id: job.item_id, action, value });
      if (result.ok) router.refresh();
      else setError(result.error);
    });

  const dialled = job.site_phone?.replace(/[^\d+]/g, "");
  const firstName = job.site_contact?.split(" ")[0];
  const total = job.units_total ?? 0;
  const done = Number(fitted) || 0;
  const complete = total > 0 && done >= total;

  return (
    <>
      {dialled && (
        <a className="btn b-call" href={`tel:${dialled}`}>
          📞 Call {firstName ?? "the site"}
        </a>
      )}

      {job.contacted ? (
        <div className="done">✓ Contacted {job.contacted}</div>
      ) : (
        <button className="btn b-main" disabled={pending} onClick={() => run("contacted")}>
          ✓ I&rsquo;ve contacted the customer
        </button>
      )}

      {job.booked ? (
        <div className="done">
          ✓ Booked{job.scheduled ? ` for ${job.scheduled}` : ""}
        </div>
      ) : (
        <button className="btn b-alt" disabled={pending} onClick={() => run("booked")}>
          📅 Book the install in
        </button>
      )}

      {/* One number, not 105 checkboxes. Shown only on multi-unit jobs, where a
          part-finished install is otherwise indistinguishable from an untouched
          one for weeks. */}
      {job.show_counter && (
        <div className="prog">
          <div className="lbl">
            <span>Units fitted</span>
            <span className="sub">
              {done} of {total}
            </span>
          </div>
          <div className="bar">
            <i
              className={complete ? "full" : ""}
              style={{ width: `${total ? Math.min(100, (done / total) * 100) : 0}%` }}
            />
          </div>
          <div className="count" style={{ marginTop: 10 }}>
            <input
              inputMode="numeric"
              aria-label="Units fitted so far"
              value={fitted}
              onChange={(e) => setFitted(e.target.value.replace(/\D/g, ""))}
            />
            <button
              className="btn b-alt"
              disabled={pending || !fitted}
              onClick={() => run("progress", Number(fitted))}
            >
              Update
            </button>
          </div>
        </div>
      )}

      {/* Fitting the last unit and finishing the job are different events, so
          the counter never auto-completes. */}
      <button className="btn b-main" disabled={pending} onClick={() => run("completed")}>
        ✓ Install complete
      </button>

      <button className="btn b-warn" disabled={pending} onClick={() => run("blocked")}>
        ⚠ Can&rsquo;t proceed — tell Navtek why
      </button>

      {error && (
        <div className="flat" style={{ color: "var(--red)" }}>
          That didn&rsquo;t save: {error}. Try again in a moment.
        </div>
      )}
    </>
  );
}
