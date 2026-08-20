import Nav from "../Nav";
import NoAccess from "../NoAccess";
import { Pager, pageParam } from "../ui";
import { getActivity } from "@/lib/api";
import { when } from "@/lib/format";
import { requireViewer, sessionToken } from "@/lib/auth";

export const metadata = { title: "Activity · Navtek" };

export const dynamic = "force-dynamic";

/** The audit trail. The data was always collected — installer views and
 * write-backs, failed sign-ins, SLA breaches, unrecognised order reasons —
 * this is the window onto it. Read-only by construction. Each table pages
 * independently (?events= / ?ledger= / ?reasons=); they used to cap at
 * their newest rows with no way further back. */

const ACTION_LABEL: Record<string, string> = {
  viewed: "👁 Opened their portal",
  contacted: "☎ Contacted the customer",
  booked: "📅 Booked the install",
  progress: "🔧 Updated units fitted",
  completed: "✅ Marked install complete",
  blocked: "⚠ Can't proceed",
  login_failed: "🚫 Failed sign-in",
  sla_breach: "⏰ SLA breach recorded",
  escalated: "🚨 Escalated on the board",
  sms_sent: "📱 SMS sent",
};

function summary(payload: Record<string, unknown>): string {
  if (!payload || typeof payload !== "object") return "";
  return Object.entries(payload)
    .filter(([, v]) => v !== null && v !== "" && typeof v !== "object")
    .slice(0, 4)
    .map(([k, v]) => `${k}: ${v}`)
    .join(" · ");
}

export default async function ActivityPage({
  searchParams,
}: {
  searchParams: Promise<{ events?: string; ledger?: string; reasons?: string }>;
}) {
  const [{ user, realUser }, params] = await Promise.all([
    requireViewer(),
    searchParams,
  ]);
  if (!user.is_admin) {
    return (
      <>
        <Nav current="/activity" user={user} realUser={realUser} />
        <NoAccess user={user} need="Admin" />
      </>
    );
  }

  const page = {
    events: pageParam(params.events),
    ledger: pageParam(params.ledger),
    reasons: pageParam(params.reasons),
  };
  const session = await sessionToken();
  const data = session
    ? await getActivity(session, {
        events: (page.events - 1) * 50,
        notifications: (page.ledger - 1) * 50,
        reasons: (page.reasons - 1) * 50,
      })
    : null;
  const size = data?.page_size ?? 50;
  const pagesOf = (total: number) => Math.max(1, Math.ceil(total / size));

  // Each pager keeps the other two tables where they are.
  const href = (over: Partial<typeof page>) => {
    const merged = { ...page, ...over };
    const search = new URLSearchParams();
    if (merged.events > 1) search.set("events", String(merged.events));
    if (merged.ledger > 1) search.set("ledger", String(merged.ledger));
    if (merged.reasons > 1) search.set("reasons", String(merged.reasons));
    const text = search.toString();
    return text ? `/activity?${text}` : "/activity";
  };

  return (
    <>
      <Nav current="/activity" user={user} realUser={realUser} />
      <div className="admin">
        <div className="head">
          <h1>Activity</h1>
          <p>
            What installers did and when, straight from the audit trail — the
            thing to check when someone says &ldquo;I called them weeks
            ago&rdquo; and the SLA report disagrees. Plus failed sign-ins and
            anything the parser flagged for a human.
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
              <h2>Events</h2>
              {data.events.length === 0 ? (
                <p className="empty">
                  {page.events > 1 ? "Nothing this far back." : "Nothing recorded yet."}
                </p>
              ) : (
                <>
                  <div className="scroll-x">
                    <table className="rows">
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
                            <td data-label="When" className="num">{when(e.created_at)}</td>
                            <td data-label="What">{ACTION_LABEL[e.action] ?? e.action}</td>
                            <td data-label="Detail" style={{ color: "var(--mid)" }}>
                              {e.monday_item_id ? `item ${e.monday_item_id} · ` : ""}
                              {summary(e.payload)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pager page={page.events} pages={pagesOf(data.events_total)}
                         total={data.events_total} unit="events"
                         hrefFor={(p) => href({ events: p })} />
                </>
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
                <p className="empty">
                  {page.ledger > 1
                    ? "Nothing this far back."
                    : "Nothing claimed yet. That's the good outcome."}
                </p>
              ) : (
                <>
                  <div className="scroll-x">
                    <table className="rows">
                      <thead>
                        <tr><th>When</th><th>Job</th><th>Kind</th><th>Detail</th></tr>
                      </thead>
                      <tbody>
                        {data.notifications.map((b, i) => (
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
                  <Pager page={page.ledger} pages={pagesOf(data.notifications_total)}
                         total={data.notifications_total} unit="entries"
                         hrefFor={(p) => href({ ledger: p })} />
                </>
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
                <p className="empty">
                  {page.reasons > 1 ? "Nothing this far back." : "None seen."}
                </p>
              ) : (
                <>
                  <div className="scroll-x">
                    <table className="rows">
                      <thead>
                        <tr><th>Seen</th><th>Order reason</th><th>Order</th></tr>
                      </thead>
                      <tbody>
                        {data.unknown_order_reasons.map((r, i) => (
                          <tr key={i}>
                            <td data-label="Seen" className="num">{when(r.seen_at)}</td>
                            <td data-label="Order reason" style={{ fontWeight: 600 }}>
                              {r.order_reason}
                            </td>
                            <td data-label="Order" className="mono"
                                style={{ color: "var(--mid)" }}>
                              {r.opportunity_id ?? r.file_name ?? "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pager page={page.reasons} pages={pagesOf(data.reasons_total)}
                         total={data.reasons_total} unit="reasons"
                         hrefFor={(p) => href({ reasons: p })} />
                </>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}
