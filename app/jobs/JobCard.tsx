import type { Job } from "@/lib/api";
import JobActions from "./JobActions";
import { fmtDate } from "./dates";

/**
 * One job, as a tappable card. Shared between the magic-link portal at
 * /j/[token] and the logged-in portal at /portal — same template, same code
 * path, exactly as the signed-off prototypes were built.
 */

const SLA_DAYS = 2;

function chip(job: Job) {
  if (job.state === "waiting") {
    return { cls: "c-grey", text: "⏳ With provisioning" };
  }
  if (job.booked) {
    if (job.show_counter && job.units_installed > 0 && job.units_installed < (job.units_total ?? 0)) {
      return {
        cls: "c-part",
        text: `🔧 ${job.units_installed} of ${job.units_total} fitted`,
      };
    }
    return { cls: "c-green", text: `📅 Booked${job.scheduled ? ` ${fmtDate(job.scheduled)}` : ""}` };
  }
  if (job.contacted) {
    return { cls: "c-blue", text: "☎ Contacted — no date booked yet" };
  }
  const days = job.overdue_days ?? 0;
  if (days > SLA_DAYS) {
    return { cls: "c-red", text: `⚠ Contact overdue — ${days} business days` };
  }
  return { cls: "c-amber", text: `Contact the customer — day ${days} of ${SLA_DAYS}` };
}

export default function JobCard({
  job,
  token,
  readOnly = false,
}: {
  job: Job;
  token?: string;
  /** Admin preview: show the card exactly as the installer sees it, minus the
   * buttons — a preview must never book, complete or block a real job. */
  readOnly?: boolean;
}) {
  const tag = chip(job);
  const units = job.units_total ? `${job.units_total} units` : null;

  return (
    <details className="card">
      <summary>
        <div className="cust">{job.customer}</div>
        {job.site_address && <div className="loc">{job.site_address}</div>}
        {units && <div className="kit">{units}</div>}
        <div className="meta">
          {job.dispatched ? `Dispatched ${fmtDate(job.dispatched)}` : "Not yet dispatched"}
          {job.opportunity_id ? ` · ${job.opportunity_id}` : ""}
        </div>
        <span className={`chip ${tag.cls}`}>{tag.text}</span>
        <span className="more">Tap for details ›</span>
      </summary>

      <div className="body">
        <div className="facts">
          {units && (
            <div className="row">
              <span className="k">Equipment</span>
              <span className="v">{units}</span>
            </div>
          )}
          <div className="row">
            <span className="k">Dispatched</span>
            <span className="v">{fmtDate(job.dispatched) ?? "Not yet"}</span>
          </div>
          <div className="row">
            <span className="k">Site contact</span>
            <span className="v">{job.site_contact ?? "—"}</span>
          </div>
          <div className="row">
            <span className="k">Phone</span>
            <span className="v">{job.site_phone ?? "—"}</span>
          </div>
          {job.contacted && (
            <div className="row">
              <span className="k">You contacted</span>
              <span className="v">{fmtDate(job.contacted)}</span>
            </div>
          )}
        </div>

        {job.state === "waiting" ? (
          <div className="flat">Hardware not dispatched yet — nothing to do</div>
        ) : readOnly ? (
          <div className="flat">Preview — actions are disabled</div>
        ) : (
          <JobActions job={job} token={token} />
        )}
      </div>
    </details>
  );
}
