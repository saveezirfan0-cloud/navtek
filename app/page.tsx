import Nav from "./Nav";
import NoAccess from "./NoAccess";
import AutoRefresh from "./AutoRefresh";
import RecentTable from "./RecentTable";
import { getHealth, getRecent } from "@/lib/api";
import { requireViewer } from "@/lib/auth";

export const metadata = { title: "Orders · Navtek" };

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  // All three in flight together — the gate is checked when they land, and
  // health/recent carry nothing user-scoped, so fetching before the check
  // costs nothing and saves a full round trip on the most-visited page.
  const [{ user, realUser }, health, recent] = await Promise.all([
    requireViewer(),
    getHealth(),
    getRecent(),
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

  const counts = {
    read: rows.filter((r) => r.status === "read").length,
    check: rows.filter((r) => r.status === "check").length,
    failed: rows.filter((r) => r.status === "failed").length,
  };

  const warnings = health?.config_warnings ?? [];
  const notReady =
    !health || health.missing_secrets.length > 0 || health.unmapped_columns.length > 0;

  return (
    <>
      <Nav current="/" user={user} realUser={realUser} />
      <AutoRefresh seconds={30} />
      <div className="admin">
        <div className="head">
          <h1>Orders</h1>
          <p>
            Every eOrder this app has read. A row appears here within seconds of
            someone dropping a file on the eOrder column in monday.
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
          </div>
          <p className="tiny" style={{ marginTop: 10 }}>
            Counts cover the {rows.length} most recent reads.
          </p>
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
            <RecentTable rows={rows} />
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
