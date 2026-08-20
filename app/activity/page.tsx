import Nav from "../Nav";
import NoAccess from "../NoAccess";
import { getActivity } from "@/lib/api";
import { requireViewer, sessionToken } from "@/lib/auth";

export const metadata = { title: "Activity · Navtek" };

export const dynamic = "force-dynamic";

/** The audit trail. The data was always collected — installer views and
 * write-backs, failed sign-ins, SLA breaches, unrecognised order reasons —
 * this is the first window onto it. Read-only by construction. */

const ACTION_LABEL: Record<string, string> = {
  viewed: "👁 Opened their portal",
  contacted: "☎ Contacted the customer",
  booked: "📅 Booked the install",
  progress: "🔧 Updated units fitted",
  completed: "✅ Marked install complete",
  blocked: "⚠ Can't proceed",
  login_failed: "🚫 Failed sign-in",
  sla_breach: "⏰ SLA breach recorded",
  webhook_processed: "🪝 Webhook — file processed",
  webhook_skipped: "🪝 Webhook — delivery skipped",
  webhook_failed: "🪝 Webhook — delivery failed",
  file_read: "📄 eOrder read cleanly",
  file_check: "📄 eOrder read — needs a look",
  file_failed: "📄 eOrder failed to parse",
};

function when(iso: string) {
  const d = new Date(iso);
  const thisYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleString("en-AU", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    ...(thisYear ? {} : { year: "numeric" }),
  });
}

function summary(payload: Record<string, unknown>): string {
  if (!payload || typeof payload !== "object") return "";
  return Object.entries(payload)
    .filter(([, v]) => v !== null && v !== "" && typeof v !== "object")
    .slice(0, 4)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");
}

export default async function ActivityPage() {
  const { user, realUser } = await requireViewer();
  if (!user.is_admin) {
    return (
      <>
        <Nav current="/activity" user={user} realUser={realUser} />
        <NoAccess user={user} need="Admin" />
      </>
    );
  }

  const session = await sessionToken();
  const data = session ? await getActivity(session) : null;

  return (
    <>
      <Nav current="/activity" user={user} realUser={realUser} />
      <div className="admin">
        <div className="head">
          <h1>Activity</h1>
          <p>
            Everything as it happens, newest first — webhooks monday fired,
            eOrder files uploaded and read, what installers did and when,
            failed sign-ins, and anything the parser flagged for a human. The
            thing to check when someone says &ldquo;I called them weeks
            ago&rdquo; and the SLA report disagrees.
          </p>
        </div>

        {!data ? (
          <div className="panel">
            <div className="warnbox">
              <b>Couldn&rsquo;t load the activity feed.</b> The database may
              not be connected.
            </div>
          </div>
        ) : (
          <>
            <div className="panel">
              <h2>Recent events</h2>
              {data.events.length === 0 ? (
                <p className="empty">Nothing recorded yet.</p>
              ) : (
                <div className="scroll-x">
                  <table>
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>What</th>
                        <th>Detail</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.events.map((e, i) => (
                        <tr key={i}>
                          <td className="num">{when(e.created_at)}</td>
                          <td>{ACTION_LABEL[e.action] ?? e.action}</td>
                          <td style={{ color: "var(--mid)" }}>
                            {e.monday_item_id ? `item ${e.monday_item_id} · ` : ""}
                            {summary(e.payload)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="panel">
              <h2>Notification ledger</h2>
              <p>
                Every claimed send, breach and escalation — one row per
                (job, kind), ever. In shadow mode this is what the sweep
                <i> would</i> have acted on.
              </p>
              {data.notifications.length === 0 ? (
                <p className="empty">Nothing claimed yet. That&rsquo;s the good outcome.</p>
              ) : (
                <div className="scroll-x">
                  <table>
                    <thead>
                      <tr><th>When</th><th>Job</th><th>Kind</th><th>Detail</th></tr>
                    </thead>
                    <tbody>
                      {data.notifications.map((b, i) => (
                        <tr key={i}>
                          <td className="num">{when(b.sent_at)}</td>
                          <td>item {b.monday_item_id}</td>
                          <td className="mono">{b.kind}</td>
                          <td style={{ color: "var(--mid)" }}>{summary(b.payload)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="panel">
              <h2>Unrecognised order reasons</h2>
              <p>
                Order reasons outside the known ACV list produce no ACV and no
                error — that&rsquo;s invisible until targets look light, so
                every one lands here for someone to look at (brief §4.1).
              </p>
              {data.unknown_order_reasons.length === 0 ? (
                <p className="empty">None seen.</p>
              ) : (
                <div className="scroll-x">
                  <table>
                    <thead>
                      <tr><th>Seen</th><th>Order reason</th><th>Order</th></tr>
                    </thead>
                    <tbody>
                      {data.unknown_order_reasons.map((r, i) => (
                        <tr key={i}>
                          <td className="num">{when(r.seen_at)}</td>
                          <td style={{ fontWeight: 600 }}>{r.order_reason}</td>
                          <td className="mono" style={{ color: "var(--mid)" }}>
                            {r.opportunity_id ?? r.file_name ?? "—"}
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
