import { getJobs, type Job } from "@/lib/api";
import JobActions from "./JobActions";

export const dynamic = "force-dynamic";

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
    return { cls: "c-green", text: `📅 Booked${job.scheduled ? ` ${job.scheduled}` : ""}` };
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

function Card({ job, token }: { job: Job; token: string }) {
  const tag = chip(job);
  const units = job.units_total ? `${job.units_total} units` : null;

  return (
    <details className="card">
      <summary>
        <div className="cust">{job.customer}</div>
        {job.site_address && <div className="loc">{job.site_address}</div>}
        {units && <div className="kit">{units}</div>}
        <div className="meta">
          {job.dispatched ? `Dispatched ${job.dispatched}` : "Not yet dispatched"}
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
            <span className="v">{job.dispatched ?? "Not yet"}</span>
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
              <span className="v">{job.contacted}</span>
            </div>
          )}
        </div>

        {job.state === "waiting" ? (
          <div className="flat">Hardware not dispatched yet — nothing to do</div>
        ) : (
          <JobActions job={job} token={token} />
        )}
      </div>
    </details>
  );
}

export default async function Portal({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const data = await getJobs(token);

  if (!data) {
    return (
      <div className="wrap">
        <div className="notice">
          <h2>This link no longer works</h2>
          <p>
            Ask Navtek to send you a new one — links are reissued when an account
            changes.
          </p>
        </div>
      </div>
    );
  }

  const { account, action_needed, waiting, overdue } = data;
  const total = action_needed.length;

  return (
    <div className="wrap">
      <header>
        <div className="brand">{account.name} · Navtek installs</div>
        <div className="who">{account.coordinator ?? account.name}</div>
        <div className="summary">
          {total === 0 ? (
            "Nothing needs your attention right now."
          ) : (
            <>
              {total} job{total === 1 ? "" : "s"} need your attention
              {overdue > 0 && (
                <>
                  {" — "}
                  <span className="hot">{overdue} past the 2-day SLA</span>
                </>
              )}
              .
            </>
          )}
        </div>
      </header>

      {action_needed.length > 0 && <div className="sect">Action needed</div>}
      {action_needed.map((job) => (
        <Card key={job.item_id} job={job} token={token} />
      ))}

      {waiting.length > 0 && <div className="sect">Waiting on hardware</div>}
      {waiting.map((job) => (
        <Card key={job.item_id} job={job} token={token} />
      ))}

      {total === 0 && waiting.length === 0 && (
        <div className="notice">
          <h2>All clear</h2>
          <p>New jobs appear here as soon as Navtek dispatch the hardware.</p>
        </div>
      )}

      <div className="foot">Navtek Australia · installer portal</div>
    </div>
  );
}
