"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { Job } from "@/lib/api";
import { submitJob } from "./actions";
import { fmtDate } from "./dates";

/** `token` present → magic-link portal; absent → logged-in installer, whose
 * session cookie is read server side by the action.
 *
 * The three irreversible-feeling taps each earned a second step: booking asks
 * for the date (that's the point of booking), blocked asks WHY (a ⚠ with no
 * reason just moves the phone call to Navtek), and complete asks for one
 * confirming tap — these run on phones in truck yards, where pockets tap
 * buttons. Everything disables while a write is in flight.
 */
export default function JobActions({ job, token }: { job: Job; token?: string }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [fitted, setFitted] = useState(String(job.units_installed || ""));
  const [mode, setMode] = useState<null | "book" | "block" | "complete">(null);
  const [bookDate, setBookDate] = useState("");
  const [note, setNote] = useState("");

  const run = (
    action: "contacted" | "booked" | "progress" | "completed" | "blocked",
    value?: string | number,
    reason?: string,
  ) =>
    start(async () => {
      setError(null);
      const result = await submitJob({
        token, item_id: job.item_id, action, value, note: reason,
      });
      if (result.ok) {
        setMode(null);
        router.refresh();
      } else setError(result.error);
    });

  const dialled = job.site_phone?.replace(/[^\d+]/g, "");
  const firstName = job.site_contact?.split(" ")[0];
  const total = job.units_total ?? 0;
  const done = Number(fitted) || 0;
  const overTotal = total > 0 && done > total;
  const complete = total > 0 && done >= total && !overTotal;

  return (
    <>
      {dialled && (
        <a className="btn b-call" href={`tel:${dialled}`}>
          📞 Call {firstName ?? "the site"}
        </a>
      )}

      {job.contacted ? (
        <div className="done">✓ Contacted {fmtDate(job.contacted)}</div>
      ) : (
        <button className="btn b-main" disabled={pending} onClick={() => run("contacted")}>
          ✓ I&rsquo;ve contacted the customer
        </button>
      )}

      {job.booked ? (
        <div className="done">
          ✓ Booked{job.scheduled ? ` for ${fmtDate(job.scheduled)}` : ""}
        </div>
      ) : mode === "book" ? (
        <div className="ask">
          <label htmlFor={`book-${job.item_id}`}>When is the install booked for?</label>
          <input
            id={`book-${job.item_id}`}
            type="date"
            value={bookDate}
            onChange={(e) => setBookDate(e.target.value)}
          />
          <div className="ask-row">
            <button
              className="btn b-alt"
              disabled={pending}
              onClick={() => run("booked", bookDate || undefined)}
            >
              {bookDate ? `Book for ${fmtDate(bookDate)}` : "Book — no date yet"}
            </button>
            <button className="btn b-plain" disabled={pending} onClick={() => setMode(null)}>
              Back
            </button>
          </div>
        </div>
      ) : (
        <button className="btn b-alt" disabled={pending} onClick={() => setMode("book")}>
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
              onChange={(e) => setFitted(e.target.value.replace(/\D/g, "").slice(0, 4))}
            />
            <button
              className="btn b-alt"
              disabled={pending || !fitted || overTotal}
              onClick={() => run("progress", done)}
            >
              Update
            </button>
          </div>
          {overTotal && (
            <div className="flat" style={{ color: "var(--red)" }}>
              That&rsquo;s more than the {total} units on this job.
            </div>
          )}
        </div>
      )}

      {/* Fitting the last unit and finishing the job are different events, so
          the counter never auto-completes. */}
      {mode === "complete" ? (
        <div className="ask">
          <div className="ask-row">
            <button className="btn b-main" disabled={pending} onClick={() => run("completed")}>
              ✓ Yes — the install is complete
            </button>
            <button className="btn b-plain" disabled={pending} onClick={() => setMode(null)}>
              Not yet
            </button>
          </div>
        </div>
      ) : (
        <button className="btn b-main" disabled={pending} onClick={() => setMode("complete")}>
          ✓ Install complete
        </button>
      )}

      {mode === "block" ? (
        <div className="ask">
          <label htmlFor={`why-${job.item_id}`}>What&rsquo;s stopping you?</label>
          <textarea
            id={`why-${job.item_id}`}
            rows={3}
            placeholder="e.g. vehicle not on site, no keys, customer wants a different day…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="ask-row">
            <button
              className="btn b-warn"
              disabled={pending || !note.trim()}
              onClick={() => run("blocked", undefined, note.trim())}
            >
              Send to Navtek
            </button>
            <button className="btn b-plain" disabled={pending} onClick={() => setMode(null)}>
              Back
            </button>
          </div>
        </div>
      ) : (
        <button className="btn b-warn" disabled={pending} onClick={() => setMode("block")}>
          ⚠ Can&rsquo;t proceed — tell Navtek why
        </button>
      )}

      {error && (
        <div className="flat" style={{ color: "var(--red)" }}>
          That didn&rsquo;t save: {error}. Try again in a moment.
        </div>
      )}
    </>
  );
}
