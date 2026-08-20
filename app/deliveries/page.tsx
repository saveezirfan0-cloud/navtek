import Link from "next/link";
import AutoRefresh from "../AutoRefresh";
import Nav from "../Nav";
import NoAccess from "../NoAccess";
import { Pager, Pill, pageParam } from "../ui";
import { getHealth, getWebhookLog } from "@/lib/api";
import { mondayItemUrl, when } from "@/lib/format";
import { requireViewer } from "@/lib/auth";

export const metadata = { title: "Deliveries · Navtek" };

export const dynamic = "force-dynamic";

/** The webhook delivery log — every call monday made, paginated server side.
 * The outcome chips and the search box are pushed into the query, so they
 * narrow the whole log, not the page that happened to load. */

const PAGE_SIZE = 25;
const OUTCOMES = ["processed", "skipped", "failed"] as const;

export default async function DeliveriesPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string; outcome?: string; q?: string }>;
}) {
  const [{ user, realUser }, params, health] = await Promise.all([
    requireViewer(),
    searchParams,
    getHealth(),
  ]);
  if (!user.can_orders && !user.is_admin) {
    return (
      <>
        <Nav current="/deliveries" user={user} realUser={realUser} />
        <NoAccess user={user} need="Orders" />
      </>
    );
  }

  const page = pageParam(params.page);
  const outcome = OUTCOMES.find((o) => o === params.outcome) ?? "";
  const q = (params.q ?? "").trim();
  const data = await getWebhookLog(PAGE_SIZE, (page - 1) * PAGE_SIZE, {
    outcome,
    q,
  });
  const hooks = data.webhooks ?? [];
  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const filtered = Boolean(outcome || q);

  const href = (over: { page?: number; outcome?: string; q?: string }) => {
    const merged = {
      page: over.page ?? 1, // a filter change starts from the newest rows
      outcome: over.outcome ?? outcome,
      q: over.q ?? q,
    };
    const search = new URLSearchParams();
    if (merged.page > 1) search.set("page", String(merged.page));
    if (merged.outcome) search.set("outcome", merged.outcome);
    if (merged.q) search.set("q", merged.q);
    const text = search.toString();
    return text ? `/deliveries?${text}` : "/deliveries";
  };

  return (
    <>
      {/* Only the unfiltered live page refreshes itself — filtered and
          history views hold still while someone reads them. */}
      {page === 1 && !filtered && <AutoRefresh seconds={15} />}
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
          ) : (
            <>
              <div className="table-tools">
                <form action="/deliveries" method="get">
                  {outcome && <input type="hidden" name="outcome" value={outcome} />}
                  <input
                    className="field"
                    style={{ marginBottom: 0, maxWidth: 260 }}
                    type="search"
                    name="q"
                    defaultValue={q}
                    placeholder="Search order, ID, reason…"
                    aria-label="Search the whole delivery log"
                  />
                </form>
                <div className="chips" role="group" aria-label="Filter by outcome">
                  <Link
                    className={`chip-btn ${outcome === "" ? "on" : ""}`}
                    href={href({ outcome: "" })}
                  >
                    All
                  </Link>
                  {OUTCOMES.map((o) => (
                    <Link
                      key={o}
                      className={`chip-btn ${outcome === o ? "on" : ""}`}
                      href={href({ outcome: o })}
                    >
                      {o === "processed" ? "Processed" : o === "skipped" ? "Skipped" : "Failed"}
                    </Link>
                  ))}
                </div>
                {filtered && (
                  <Link className="chip-btn" href="/deliveries">✕ Clear</Link>
                )}
              </div>

              {data.total === 0 ? (
                <p className="empty">
                  {filtered
                    ? "Nothing in the log matches that filter."
                    : "No deliveries recorded yet."}
                </p>
              ) : hooks.length === 0 ? (
                <p className="empty">
                  Nothing this far back — this view holds {data.total}{" "}
                  {data.total === 1 ? "delivery" : "deliveries"}.{" "}
                  <Link href={href({ page: 1 })}>Back to the newest</Link>.
                </p>
              ) : (
                <>
                  <div className="scroll-x">
                    <table className="rows">
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
                          const boardUrl = mondayItemUrl(
                            health?.monday_slug, health?.orders_board, h.monday_item_id);
                          return (
                            <tr key={i}>
                              <td data-label="Order">
                                <div style={{ fontWeight: 600 }}>
                                  {h.monday_item_id ? (
                                    <Link href={`/orders/${h.monday_item_id}`}>
                                      {h.file_name ?? `item ${h.monday_item_id}`}
                                    </Link>
                                  ) : (
                                    h.file_name ?? "—"
                                  )}
                                </div>
                                <div className="mono" style={{ color: "var(--mid)" }}>
                                  {h.opportunity_id}
                                  {h.opportunity_id && boardUrl && " · "}
                                  {boardUrl && (
                                    <a href={boardUrl} target="_blank" rel="noreferrer">
                                      open in monday ↗
                                    </a>
                                  )}
                                </div>
                              </td>
                              <td data-label="Outcome"><Pill kind={h.outcome} /></td>
                              <td data-label="Detail" style={{ color: "var(--mid)" }}>
                                {h.reason ?? h.status ?? ""}
                              </td>
                              <td data-label="When" className="num">{when(h.created_at)}</td>
                              <td data-label="Took" className="num">
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

                  <Pager
                    page={page}
                    pages={pages}
                    total={data.total}
                    unit="deliveries"
                    hrefFor={(p) => href({ page: p })}
                  />
                </>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
