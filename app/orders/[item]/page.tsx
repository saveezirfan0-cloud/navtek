import Link from "next/link";
import Nav from "../../Nav";
import NoAccess from "../../NoAccess";
import { Pill } from "../../ui";
import { getHealth, getOrderDetail } from "@/lib/api";
import { mondayItemUrl, when } from "@/lib/format";
import { requireViewer } from "@/lib/auth";

export const metadata = { title: "Order · Navtek" };

export const dynamic = "force-dynamic";

/** One order, in full. The dashboard squeezes a ⚠️ Check row's "why" into a
 * single Notes cell; this page is the whole answer — every read with its
 * warnings and changes, the full parse, and every webhook delivery. */

/** The parse's scalar facts, in the order the parser found them. Nested
 * structures (vehicle lists, per-site blocks) stay in the raw view below. */
function scalars(parsed: Record<string, unknown>): [string, string][] {
  return Object.entries(parsed)
    .filter(([, v]) =>
      v !== null && v !== "" && ["string", "number", "boolean"].includes(typeof v))
    .map(([k, v]) => [k.replaceAll("_", " "), String(v)]);
}

export default async function OrderPage({
  params,
}: {
  params: Promise<{ item: string }>;
}) {
  const [{ user, realUser }, { item }, health] = await Promise.all([
    requireViewer(),
    params,
    getHealth(),
  ]);
  if (!user.can_orders && !user.is_admin) {
    return (
      <>
        <Nav current="/" user={user} realUser={realUser} />
        <NoAccess user={user} need="Orders" />
      </>
    );
  }

  const itemId = item.replace(/[^0-9]/g, "");
  const data = itemId ? await getOrderDetail(itemId) : null;
  const reads = data?.ingests ?? [];
  const hooks = data?.webhooks ?? [];
  const latest = reads[0];
  const boardUrl = mondayItemUrl(health?.monday_slug, health?.orders_board, itemId);

  return (
    <>
      <Nav current="/" user={user} realUser={realUser} />
      <div className="admin">
        <div className="head">
          <h1>{latest?.item_name ?? latest?.file_name ?? `Item ${itemId || item}`}</h1>
          <p>
            {latest?.opportunity_id && (
              <span className="mono">{latest.opportunity_id} · </span>
            )}
            monday item {itemId || "unknown"}
            {boardUrl && (
              <>
                {" · "}
                <a href={boardUrl} target="_blank" rel="noreferrer">
                  open in monday ↗
                </a>
              </>
            )}
            {reads.length > 0 && itemId && (
              <>
                {" · "}
                {/* monday asset URLs expire hourly; the endpoint mints a
                    fresh one per click. */}
                <a href={`/api/py/eorder/file?item_id=${itemId}`}
                   target="_blank" rel="noreferrer">
                  ⬇ eOrder file
                </a>
              </>
            )}
            {" · "}
            <Link href="/">back to Orders</Link>
          </p>
        </div>

        {!data?.enabled ? (
          <div className="panel">
            <p className="empty">
              <b>Couldn&rsquo;t load this order&rsquo;s history.</b>{" "}
              {data?.database?.detail ?? "The database isn't connected."}
            </p>
          </div>
        ) : reads.length === 0 && hooks.length === 0 ? (
          <div className="panel">
            <p className="empty">
              Nothing recorded for this item — no reads, no deliveries. Either
              the id is wrong or its history predates the ledger.
            </p>
          </div>
        ) : (
          <>
            <div className="panel">
              <h2>Reads</h2>
              <p>
                Every time an eOrder was read onto this row, newest first. A
                revision says what it changed; existing monday values are never
                clobbered.
              </p>
              {reads.length === 0 ? (
                <p className="empty">No reads recorded.</p>
              ) : (
                <div className="scroll-x">
                  <table className="rows">
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>Status</th>
                        <th>File</th>
                        <th>Changed</th>
                        <th>Warnings</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reads.map((r, i) => (
                        <tr key={i}>
                          <td data-label="When" className="num">{when(r.created_at)}</td>
                          <td data-label="Status"><Pill kind={r.status} /></td>
                          <td data-label="File" style={{ color: "var(--mid)" }}>
                            {r.file_name ?? "—"}
                          </td>
                          <td data-label="Changed" style={{ color: "var(--mid)" }}>
                            {r.changed_fields.length
                              ? r.changed_fields.join(", ")
                              : "—"}
                          </td>
                          <td data-label="Warnings" style={{ color: "var(--mid)" }}>
                            {r.error ?? (r.warnings.length ? r.warnings.join(" · ") : "—")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {latest && Object.keys(latest.parsed ?? {}).length > 0 && (
              <div className="panel">
                <h2>What the latest read saw</h2>
                <p>
                  The parser&rsquo;s output from {latest.file_name ?? "the file"},
                  read {when(latest.created_at)}. Blank fields are omitted.
                </p>
                <div className="scroll-x">
                  <table>
                    <tbody>
                      {scalars(latest.parsed).map(([k, v]) => (
                        <tr key={k}>
                          <td style={{ color: "var(--mid)", width: "40%" }}>{k}</td>
                          <td style={{ fontWeight: 600 }}>{v}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <details style={{ marginTop: 12 }}>
                  <summary style={{ padding: 0, fontWeight: 600, color: "var(--navy-2)" }}>
                    Full parse (raw)
                  </summary>
                  <pre className="out">{JSON.stringify(latest.parsed, null, 2)}</pre>
                </details>
              </div>
            )}

            <div className="panel">
              <h2>Webhook deliveries</h2>
              <p>
                Every call monday made about this item — including skips and
                no-file deliveries the read ledger never sees.
              </p>
              {hooks.length === 0 ? (
                <p className="empty">
                  None recorded. Deliveries older than the webhook log&rsquo;s
                  retention window fall out of this list.
                </p>
              ) : (
                <div className="scroll-x">
                  <table className="rows">
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>Outcome</th>
                        <th>Detail</th>
                        <th>Took</th>
                      </tr>
                    </thead>
                    <tbody>
                      {hooks.map((h, i) => (
                        <tr key={i}>
                          <td data-label="When" className="num">{when(h.created_at)}</td>
                          <td data-label="Outcome"><Pill kind={h.outcome} /></td>
                          <td data-label="Detail" style={{ color: "var(--mid)" }}>
                            {h.reason ?? h.status ?? ""}
                          </td>
                          <td data-label="Took" className="num">
                            {h.duration_ms ? `${(h.duration_ms / 1000).toFixed(1)}s` : "—"}
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
