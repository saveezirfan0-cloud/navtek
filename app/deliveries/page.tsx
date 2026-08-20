import Link from "next/link";
import AutoRefresh from "../AutoRefresh";
import Nav from "../Nav";
import NoAccess from "../NoAccess";
import { getWebhookLog } from "@/lib/api";
import { when } from "@/lib/format";
import { requireViewer } from "@/lib/auth";

export const metadata = { title: "Deliveries · Navtek" };

export const dynamic = "force-dynamic";

/** The webhook delivery log, moved off the dashboard onto its own tab and
 * paginated server side — the log grows by every drop, retry and cron-adjacent
 * edit forever, and the dashboard only ever showed the newest 50. */

const PAGE_SIZE = 25;

const HOOK_PILL: Record<string, [string, string]> = {
  processed: ["p-read", "Processed"],
  skipped: ["p-check", "Skipped"],
  failed: ["p-failed", "Failed"],
};

export default async function DeliveriesPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string }>;
}) {
  const [{ user, realUser }, params] = await Promise.all([
    requireViewer(),
    searchParams,
  ]);
  if (!user.can_orders && !user.is_admin) {
    return (
      <>
        <Nav current="/deliveries" user={user} realUser={realUser} />
        <NoAccess user={user} need="Orders" />
      </>
    );
  }

  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);
  const data = await getWebhookLog(PAGE_SIZE, (page - 1) * PAGE_SIZE);
  const hooks = data.webhooks ?? [];
  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));

  return (
    <>
      {/* Only the live page refreshes itself — history pages hold still so
          rows don't shift underneath someone reading back through the log. */}
      {page === 1 && <AutoRefresh seconds={15} />}
      <Nav current="/deliveries" user={user} realUser={realUser} />
      <div className="admin">
        <div className="head">
          <h1>Webhook deliveries</h1>
          <p>
            Every call monday made to this app, including the ones that changed
            nothing. monday&rsquo;s own automation log shows all of these as
            Success — a <b>Skipped</b> row here is why a drop can succeed in
            monday and still change nothing (usually the identical file was
            already read).
          </p>
        </div>

        <div className="panel">
          {!data.enabled ? (
            <p className="empty">
              <b>Nothing is being recorded.</b>{" "}
              {data.database?.detail ?? "The database isn't connected."}
            </p>
          ) : data.webhook_log_ready === false ? (
            <p className="empty">
              <b>Not recording yet.</b> Run{" "}
              <code>supabase/migrations/0004_webhook_log.sql</code> in the
              Supabase SQL Editor to switch this log on.
            </p>
          ) : data.total === 0 ? (
            <p className="empty">No deliveries recorded yet.</p>
          ) : hooks.length === 0 ? (
            <p className="empty">
              Nothing this far back — the log holds {data.total}{" "}
              {data.total === 1 ? "delivery" : "deliveries"}.{" "}
              <Link href="/deliveries">Back to the newest</Link>.
            </p>
          ) : (
            <>
              <div className="scroll-x">
                <table>
                  <thead>
                    <tr>
                      <th>Order</th>
                      <th>Outcome</th>
                      <th>Detail</th>
                      <th>When</th>
                      <th>Took</th>
                    </tr>
                  </thead>
                  <tbody>
                    {hooks.map((h, i) => {
                      const [cls, label] =
                        HOOK_PILL[h.outcome] ?? ["p-check", h.outcome];
                      return (
                        <tr key={i}>
                          <td>
                            <div style={{ fontWeight: 600 }}>
                              {h.file_name ??
                                (h.monday_item_id ? `item ${h.monday_item_id}` : "—")}
                            </div>
                            {h.opportunity_id && (
                              <div className="mono" style={{ color: "var(--mid)" }}>
                                {h.opportunity_id}
                              </div>
                            )}
                          </td>
                          <td>
                            <span className={`pill ${cls}`}>{label}</span>
                          </td>
                          <td style={{ color: "var(--mid)" }}>
                            {h.reason ?? h.status ?? ""}
                          </td>
                          <td className="num">{when(h.created_at)}</td>
                          <td className="num">
                            {h.duration_ms
                              ? `${(h.duration_ms / 1000).toFixed(1)}s`
                              : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {pages > 1 && (
                <nav className="pager" aria-label="Delivery log pages">
                  {page > 1 ? (
                    <Link className="page-btn" href={`/deliveries?page=${page - 1}`}>
                      ← Newer
                    </Link>
                  ) : (
                    <span className="page-btn off">← Newer</span>
                  )}
                  <span className="page-where">
                    Page {page} of {pages} · {data.total} deliveries
                  </span>
                  {page < pages ? (
                    <Link className="page-btn" href={`/deliveries?page=${page + 1}`}>
                      Older →
                    </Link>
                  ) : (
                    <span className="page-btn off">Older →</span>
                  )}
                </nav>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
