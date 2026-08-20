import Link from "next/link";
import AutoRefresh from "./AutoRefresh";
import CsvButton from "./CsvButton";
import Nav from "./Nav";
import NoAccess from "./NoAccess";
import { Pager, Pill, pageParam } from "./ui";
import ActivityChart from "./ActivityChart";
import { getHealth, getRecent, getStats } from "@/lib/api";
import { mondayItemUrl, when } from "@/lib/format";
import { requireViewer } from "@/lib/auth";

export const metadata = { title: "Orders · Navtek" };

export const dynamic = "force-dynamic";

const PAGE_SIZE = 25;
const STATUSES = ["read", "check", "failed"] as const;

export default async function Dashboard({
  searchParams,
}: {
  searchParams: Promise<{ page?: string; status?: string; q?: string }>;
}) {
  // All in flight together — the gate is checked when they land, and
  // health/recent carry nothing user-scoped, so fetching before the check
  // costs nothing and saves a full round trip on the most-visited page.
  const params = await searchParams;
  const page = pageParam(params.page);
  const status = STATUSES.find((s) => s === params.status) ?? "";
  const q = (params.q ?? "").trim();

  const [{ user, realUser }, health, recent, stats] = await Promise.all([
    requireViewer(),
    getHealth(),
    getRecent({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, status, q }),
    getStats(30),
  ]);
  if (!user.can_orders && !user.is_admin) {
    return (
      <>
        <Nav current="/" user={user} realUser={realUser} />
        <NoAccess user={user} need="Orders" />
      </>
    );
  }

  const rows = recent.ingests;
  const pages = Math.max(1, Math.ceil(recent.total / PAGE_SIZE));
  const filtered = Boolean(status || q);

  const href = (over: { page?: number; status?: string; q?: string }) => {
    const merged = {
      page: over.page ?? 1, // a filter change starts from the newest rows
      status: over.status ?? status,
      q: over.q ?? q,
    };
    const search = new URLSearchParams();
    if (merged.page > 1) search.set("page", String(merged.page));
    if (merged.status) search.set("status", merged.status);
    if (merged.q) search.set("q", merged.q);
    const text = search.toString();
    return text ? `/?${text}` : "/";
  };

  const warnings = health?.config_warnings ?? [];
  const notReady =
    !health || health.missing_secrets.length > 0 || health.unmapped_columns.length > 0;

  return (
    <>
      {page === 1 && !filtered && <AutoRefresh seconds={15} />}
      <Nav current="/" user={user} realUser={realUser} />
      <div className="admin">
        <div className="head">
          <h1>Orders</h1>
          <p>
            Every eOrder this app has read. A row appears here within seconds of
            someone dropping a file on the eOrder column in monday — this page
            refreshes itself.
          </p>
        </div>

        {warnings.length > 0 && (
          <div className="panel">
            {warnings.map((w, i) => (
              <div className="warnbox" key={i} style={{ marginBottom: 0 }}>
                <b>Check a setting.</b> {w}
              </div>
            ))}
          </div>
        )}

        {notReady && (
          <div className="panel">
            <div className="warnbox">
              <b>Not finished setting up.</b>{" "}
              {!health
                ? "The Python API isn't responding."
                : health.missing_secrets.length > 0
                  ? `Missing environment variables: ${health.missing_secrets.join(", ")}.`
                  : `${health.unmapped_columns.length} monday columns aren't mapped yet.`}{" "}
              Go to <a href="/setup">Setup</a>.
            </div>
          </div>
        )}

        <div className="panel">
          <div className="grid">
            <div className="stat">
              <div className="v">{recent.counts?.read ?? 0}</div>
              <div className="k">Read cleanly</div>
            </div>
            <div className="stat">
              <div className="v">{recent.counts?.check ?? 0}</div>
              <div className="k">Need a look</div>
            </div>
            <div className="stat">
              <div className="v">{recent.counts?.failed ?? 0}</div>
              <div className="k">Failed</div>
            </div>
            <div className="stat">
              <div className="v">{health?.write_order_type ? "On" : "Off"}</div>
              <div className="k">Writing Order Type</div>
            </div>
            <div className="stat">
              <div className="v">{health?.allow_duplicate_files ? "On" : "Off"}</div>
              <div className="k">Duplicate re-reads (testing)</div>
            </div>
          </div>
          <p className="tiny" style={{ marginTop: 10 }}>
            Counts cover every read ever recorded.
          </p>
        </div>

        {stats && (
          <div className="panel">
            <h2>Last 30 days</h2>
            <p>
              One bar per day — how much arrived, and how much of it needed a
              person.
            </p>
            <ActivityChart days={stats.days} />
            <div className="grid" style={{ marginTop: 14 }}>
              <div className="stat">
                <div className="v">
                  {stats.success_rate === null
                    ? "—"
                    : `${Math.round(stats.success_rate * 100)}%`}
                </div>
                <div className="k">Read cleanly, first time</div>
              </div>
              <div className="stat">
                <div className="v">
                  {stats.median_ms === null
                    ? "—"
                    : `${(stats.median_ms / 1000).toFixed(1)}s`}
                </div>
                <div className="k">Median file-to-board time</div>
              </div>
              <div className="stat">
                <div className="v">
                  {stats.p90_ms === null
                    ? "—"
                    : `${(stats.p90_ms / 1000).toFixed(1)}s`}
                </div>
                <div className="k">Slowest 10% take at least</div>
              </div>
            </div>
          </div>
        )}

        <div className="panel">
          <h2>Reads</h2>
          {!recent.enabled ? (
            <p className="empty">
              <b>Nothing is being recorded.</b>{" "}
              {recent.database?.detail ??
                "The database isn't connected."}{" "}
              {recent.database?.state === "not_configured" && (
                <>
                  Set <code>SUPABASE_URL</code> and{" "}
                  <code>SUPABASE_SERVICE_KEY</code> in Vercel, then redeploy.
                </>
              )}
              <br />
              <span style={{ fontSize: 13.5 }}>
                This does not stop eOrders being read — monday is still written
                to. What is lost is the duplicate check and this history.
              </span>
            </p>
          ) : (
            <>
              <div className="table-tools">
                <form action="/" method="get">
                  {status && <input type="hidden" name="status" value={status} />}
                  <input
                    className="field"
                    style={{ marginBottom: 0, maxWidth: 260 }}
                    type="search"
                    name="q"
                    defaultValue={q}
                    placeholder="Search order, ID, note…"
                    aria-label="Search every recorded read"
                  />
                </form>
                <div className="chips" role="group" aria-label="Filter by status">
                  <Link className={`chip-btn ${status === "" ? "on" : ""}`}
                        href={href({ status: "" })}>
                    All
                  </Link>
                  {STATUSES.map((s) => (
                    <Link key={s} className={`chip-btn ${status === s ? "on" : ""}`}
                          href={href({ status: s })}>
                      {s === "read" ? "Read" : s === "check" ? "Check" : "Failed"}
                    </Link>
                  ))}
                </div>
                <CsvButton rows={rows} />
              </div>

              {recent.total === 0 ? (
                <p className="empty">
                  {filtered ? (
                    "Nothing recorded matches that filter."
                  ) : (
                    <>
                      Nothing read yet. Drop an eOrder onto the eOrder column of
                      a row in TN Orders and it will appear here.
                    </>
                  )}
                </p>
              ) : rows.length === 0 ? (
                <p className="empty">
                  Nothing this far back.{" "}
                  <Link href={href({ page: 1 })}>Back to the newest</Link>.
                </p>
              ) : (
                <>
                  <div className="scroll-x">
                    <table className="rows">
                      <thead>
                        <tr>
                          <th>Order</th>
                          <th>Status</th>
                          <th>Notes</th>
                          <th>When</th>
                          <th>Took</th>
                          <th>File</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r, i) => {
                          const boardUrl = mondayItemUrl(
                            health?.monday_slug, health?.orders_board, r.monday_item_id);
                          return (
                            <tr key={i}>
                              <td data-label="Order">
                                <div style={{ fontWeight: 600 }}>
                                  {r.monday_item_id ? (
                                    <Link href={`/orders/${r.monday_item_id}`}>
                                      {r.item_name ?? r.file_name ?? `item ${r.monday_item_id}`}
                                    </Link>
                                  ) : (
                                    r.item_name ?? r.file_name ?? "—"
                                  )}
                                </div>
                                <div className="mono" style={{ color: "var(--mid)" }}>
                                  {r.opportunity_id}
                                  {r.opportunity_id && boardUrl && " · "}
                                  {boardUrl && (
                                    <a href={boardUrl} target="_blank" rel="noreferrer">
                                      open in monday ↗
                                    </a>
                                  )}
                                </div>
                              </td>
                              <td data-label="Status"><Pill kind={r.status} /></td>
                              <td data-label="Notes" style={{ color: "var(--mid)" }}>
                                {r.error ??
                                  [...r.changed_fields, ...r.warnings].slice(0, 3).join(" · ") ??
                                  ""}
                              </td>
                              <td data-label="When" className="num">{when(r.created_at)}</td>
                              <td data-label="Took" className="num">
                                {r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : "—"}
                              </td>
                              <td data-label="File">
                                {r.monday_item_id ? (
                                  // monday asset URLs expire hourly, so the endpoint
                                  // mints a fresh one per click — never embed one here.
                                  <a
                                    className="filelink"
                                    href={`/api/py/eorder/file?item_id=${r.monday_item_id}`}
                                    title={r.file_name ?? "Download the eOrder file"}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    ⬇ View
                                  </a>
                                ) : (
                                  "—"
                                )}
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
                    total={recent.total}
                    unit="reads"
                    hrefFor={(p) => href({ page: p })}
                  />
                </>
              )}

              <p className="tiny" style={{ marginTop: 10 }}>
                A drop that changed nothing (a duplicate file, a no-file
                delivery) never lands here — see{" "}
                <Link href="/deliveries">Deliveries</Link> for every call
                monday made.
              </p>
            </>
          )}
        </div>

        <div className="foot">
          {health?.build
            ? `Build ${health.build.version}${
                health.build.commit ? ` · ${health.build.commit}` : ""
              }`
            : "Build unknown — the Python API is not responding"}
        </div>
      </div>
    </>
  );
}
