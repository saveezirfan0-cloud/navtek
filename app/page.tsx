import AutoRefresh from "./AutoRefresh";
import Nav from "./Nav";
import NoAccess from "./NoAccess";
import { getHealth, getRecent } from "@/lib/api";
import { requireViewer } from "@/lib/auth";

export const dynamic = "force-dynamic";

const PILL: Record<string, [string, string]> = {
  read: ["p-read", "Read"],
  check: ["p-check", "Check"],
  failed: ["p-failed", "Failed"],
};

const HOOK_PILL: Record<string, [string, string]> = {
  processed: ["p-read", "Processed"],
  skipped: ["p-check", "Skipped"],
  failed: ["p-failed", "Failed"],
};

function when(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString("en-AU", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

export default async function Dashboard() {
  const { user, realUser } = await requireViewer();
  if (!user.can_orders && !user.is_admin) {
    return (
      <>
        <Nav current="/" user={user} realUser={realUser} />
        <NoAccess user={user} need="Orders" />
      </>
    );
  }

  const [health, recent] = await Promise.all([getHealth(), getRecent()]);
  const rows = recent.ingests;

  const counts = {
    read: rows.filter((r) => r.status === "read").length,
    check: rows.filter((r) => r.status === "check").length,
    failed: rows.filter((r) => r.status === "failed").length,
  };

  const warnings = health?.config_warnings ?? [];
  const notReady =
    !health || health.missing_secrets.length > 0 || health.unmapped_columns.length > 0;

  const hooks = recent.webhooks ?? [];

  return (
    <>
      <AutoRefresh seconds={15} />
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
              <div className="v">{counts.read}</div>
              <div className="k">Read cleanly</div>
            </div>
            <div className="stat">
              <div className="v">{counts.check}</div>
              <div className="k">Need a look</div>
            </div>
            <div className="stat">
              <div className="v">{counts.failed}</div>
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
        </div>

        <div className="panel">
          <h2>Recent reads</h2>
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
          ) : rows.length === 0 ? (
            <p className="empty">
              Nothing read yet. Drop an eOrder onto the eOrder column of a row in
              TN Orders and it will appear here.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Status</th>
                  <th>Notes</th>
                  <th>When</th>
                  <th>Took</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const [cls, label] = PILL[r.status] ?? ["p-check", r.status];
                  return (
                    <tr key={i}>
                      <td>
                        <div style={{ fontWeight: 600 }}>
                          {r.item_name ?? r.file_name ?? "—"}
                        </div>
                        {r.opportunity_id && (
                          <div className="mono" style={{ color: "var(--mid)" }}>
                            {r.opportunity_id}
                          </div>
                        )}
                        {r.monday_item_id && (
                          <a
                            href={`/api/py/eorder/file?item_id=${r.monday_item_id}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{ fontSize: 13 }}
                          >
                            📄 eOrder file
                          </a>
                        )}
                      </td>
                      <td>
                        <span className={`pill ${cls}`}>{label}</span>
                      </td>
                      <td style={{ color: "var(--mid)" }}>
                        {r.error ??
                          [...r.changed_fields, ...r.warnings].slice(0, 3).join(" · ") ??
                          ""}
                      </td>
                      <td className="num">{when(r.created_at)}</td>
                      <td className="num">
                        {r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <h2>Webhook deliveries</h2>
          <p className="empty" style={{ marginTop: 0 }}>
            Every call monday made to this app, including the ones that changed
            nothing. monday&rsquo;s own automation log shows all of these as
            Success — a <b>Skipped</b> row here is why a drop can succeed in
            monday and still change nothing (usually the identical file was
            already read).
          </p>
          {recent.enabled && recent.webhook_log_ready === false ? (
            <p className="empty">
              <b>Not recording yet.</b> Run{" "}
              <code>supabase/migrations/0004_webhook_log.sql</code> in the
              Supabase SQL Editor to switch this log on.
            </p>
          ) : hooks.length === 0 ? (
            <p className="empty">No deliveries recorded yet.</p>
          ) : (
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
                  const [cls, label] = HOOK_PILL[h.outcome] ?? ["p-check", h.outcome];
                  return (
                    <tr key={i}>
                      <td>
                        <div style={{ fontWeight: 600 }}>
                          {h.file_name ?? (h.monday_item_id ? `item ${h.monday_item_id}` : "—")}
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
                        {h.duration_ms ? `${(h.duration_ms / 1000).toFixed(1)}s` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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
