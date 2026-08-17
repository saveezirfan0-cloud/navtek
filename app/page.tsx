import Nav from "./Nav";
import { getHealth, getRecent } from "@/lib/api";

export const dynamic = "force-dynamic";

const PILL: Record<string, [string, string]> = {
  read: ["p-read", "Read"],
  check: ["p-check", "Check"],
  failed: ["p-failed", "Failed"],
};

function when(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString("en-AU", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

export default async function Dashboard() {
  const [health, recent] = await Promise.all([getHealth(), getRecent()]);
  const rows = recent.ingests;

  const counts = {
    read: rows.filter((r) => r.status === "read").length,
    check: rows.filter((r) => r.status === "check").length,
    failed: rows.filter((r) => r.status === "failed").length,
  };

  const notReady =
    !health || health.missing_secrets.length > 0 || health.unmapped_columns.length > 0;

  return (
    <>
      <Nav current="/" />
      <div className="admin">
        <div className="head">
          <h1>Orders</h1>
          <p>
            Every eOrder this app has read. A row appears here within seconds of
            someone dropping a file on the eOrder column in monday.
          </p>
        </div>

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
          </div>
        </div>

        <div className="panel">
          <h2>Recent reads</h2>
          {!recent.enabled ? (
            <p className="empty">
              The database isn&rsquo;t connected, so nothing is being recorded.
              Check <code>SUPABASE_URL</code> and <code>SUPABASE_SERVICE_KEY</code>.
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
      </div>
    </>
  );
}
