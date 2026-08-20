import Nav from "../Nav";
import NoAccess from "../NoAccess";
import { Pill } from "../ui";
import { getHealth, getSlaPreview } from "@/lib/api";
import { mondayItemUrl, when } from "@/lib/format";
import { requireViewer, sessionToken } from "@/lib/auth";

export const metadata = { title: "SLA · Navtek" };

export const dynamic = "force-dynamic";

/** The SLA console. The engine ran in shadow mode with its output buried in
 * the Activity feed; this page is what makes flipping
 * SLA_NOTIFICATIONS_ENABLED a decision instead of a leap — what the engine
 * sees, per-job countdowns, and what the last sweeps claimed. Read-only by
 * construction: the preview endpoint records nothing. */

function summary(payload: Record<string, unknown>): string {
  if (!payload || typeof payload !== "object") return "";
  return Object.entries(payload)
    .filter(([, v]) => v !== null && v !== "" && typeof v !== "object")
    .slice(0, 4)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");
}

export default async function SlaPage() {
  const { user, realUser } = await requireViewer();
  if (!user.is_admin) {
    return (
      <>
        <Nav current="/sla" user={user} realUser={realUser} />
        <NoAccess user={user} need="Admin" />
      </>
    );
  }

  const session = await sessionToken();
  const [data, health] = await Promise.all([
    session ? getSlaPreview(session) : null,
    getHealth(),
  ]);

  const jobs = data?.jobs ?? [];
  const breached = jobs.filter((j) => j.status === "breached").length;
  const dueNow = jobs.filter((j) => j.status === "due_now").length;

  return (
    <>
      <Nav current="/sla" user={user} realUser={realUser} />
      <div className="admin">
        <div className="head">
          <h1>SLA</h1>
          <p>
            The contact clock: an installer must reach the customer within{" "}
            {data?.sla_business_days ?? 2} business days of dispatch, public
            holidays per their state. This page is what the engine sees right
            now — reading it changes nothing.
          </p>
        </div>

        {!data ? (
          <div className="panel">
            <div className="warnbox">
              <b>Couldn&rsquo;t load the SLA preview.</b> The database or
              monday may not be reachable.
            </div>
          </div>
        ) : (
          <>
            <div className="panel">
              {data.mode === "off" ? (
                <div className="warnbox" style={{ marginBottom: 0 }}>
                  <b>The engine is off.</b> <code>SLA_GO_LIVE_DATE</code> is
                  not set. Nothing is swept, recorded or sent — set the cutoff
                  date first, because without it day one would text every
                  installer about months-old backlog.
                </div>
              ) : data.mode === "shadow" ? (
                <div className="warnbox" style={{ marginBottom: 0 }}>
                  <b>Shadow mode.</b> The daily sweep records breaches and logs
                  what it <i>would</i> send — no SMS goes out, no status is
                  written. Read a week of the ledger below before setting{" "}
                  <code>SLA_NOTIFICATIONS_ENABLED=true</code>.
                </div>
              ) : (
                <div className="warnbox"
                     style={{ marginBottom: 0, background: "var(--green-bg)",
                              borderColor: "var(--green)" }}>
                  <b>Live.</b> Breaches escalate on the board and coordinators
                  are texted. Go-live cutoff: {data.go_live}.
                </div>
              )}
            </div>

            {data.mode !== "off" && (
              <div className="panel">
                <div className="grid">
                  <div className="stat">
                    <div className="v">{jobs.length}</div>
                    <div className="k">Jobs on the clock</div>
                  </div>
                  <div className="stat">
                    <div className="v">{breached}</div>
                    <div className="k">Past the SLA</div>
                  </div>
                  <div className="stat">
                    <div className="v">{dueNow}</div>
                    <div className="k">Due now</div>
                  </div>
                  <div className="stat">
                    <div className="v">{data.jobs_checked}</div>
                    <div className="k">Jobs checked</div>
                  </div>
                </div>
                <p className="tiny" style={{ marginTop: 10 }}>
                  Only jobs dispatched on or after {data.go_live} and not yet
                  contacted are on the clock.
                </p>
              </div>
            )}

            {data.mode !== "off" && (
              <div className="panel">
                <h2>The clock, worst first</h2>
                {jobs.length === 0 ? (
                  <p className="empty">
                    Nothing on the clock — every dispatched job inside the
                    window has been contacted. That&rsquo;s the good outcome.
                  </p>
                ) : (
                  <div className="scroll-x">
                    <table className="rows">
                      <thead>
                        <tr>
                          <th>Customer</th>
                          <th>Installer</th>
                          <th>Dispatched</th>
                          <th>Clock age</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {jobs.map((j, i) => {
                          const boardUrl = mondayItemUrl(
                            health?.monday_slug, health?.orders_board, j.item_id);
                          return (
                            <tr key={i}>
                              <td data-label="Customer">
                                <div style={{ fontWeight: 600 }}>
                                  {j.customer ?? `item ${j.item_id}`}
                                </div>
                                {boardUrl && (
                                  <div className="mono">
                                    <a href={boardUrl} target="_blank" rel="noreferrer">
                                      open in monday ↗
                                    </a>
                                  </div>
                                )}
                              </td>
                              <td data-label="Installer" style={{ color: "var(--mid)" }}>
                                {j.account} · {j.state}
                              </td>
                              <td data-label="Dispatched" className="num">{j.dispatched}</td>
                              <td data-label="Clock age" className="num">
                                {j.sla_age_business_days} business{" "}
                                {j.sla_age_business_days === 1 ? "day" : "days"}
                                {j.clock_start !== j.dispatched &&
                                  " (clock restarted on reallocation)"}
                              </td>
                              <td data-label="Status">
                                <Pill kind={j.status} label={
                                  j.status === "breached"
                                    ? `${-j.days_left} over`
                                    : j.status === "due_now"
                                      ? "Due now"
                                      : `${j.days_left} left`
                                } />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            <div className="panel">
              <h2>What recent sweeps claimed</h2>
              <p>
                The notification ledger, newest first — breaches recorded,
                sends made (or, in shadow mode, sends that would have been
                made). One row per (job, kind), ever: this is the dedup.
              </p>
              {data.ledger.length === 0 ? (
                <p className="empty">Nothing claimed yet.</p>
              ) : (
                <div className="scroll-x">
                  <table className="rows">
                    <thead>
                      <tr><th>When</th><th>Job</th><th>Kind</th><th>Detail</th></tr>
                    </thead>
                    <tbody>
                      {data.ledger.map((b, i) => (
                        <tr key={i}>
                          <td data-label="When" className="num">{when(b.sent_at)}</td>
                          <td data-label="Job">item {b.monday_item_id}</td>
                          <td data-label="Kind" className="mono">{b.kind}</td>
                          <td data-label="Detail" style={{ color: "var(--mid)" }}>
                            {summary(b.payload)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}
