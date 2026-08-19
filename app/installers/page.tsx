import Nav from "../Nav";
import NoAccess from "../NoAccess";
import { getInstallers } from "@/lib/api";
import { requireViewer } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function InstallersPage() {
  const { user, realUser } = await requireViewer();
  if (!user.is_admin) {
    return (
      <>
        <Nav current="/installers" user={user} realUser={realUser} />
        <NoAccess user={user} need="Admin" />
      </>
    );
  }

  const { accounts } = await getInstallers();

  return (
    <>
      <Nav current="/installers" user={user} realUser={realUser} />
      <div className="admin">
        <div className="head">
          <h1>Installers</h1>
          <p>
            One row per installer <b>account</b>, not per person. GPS Tech&rsquo;s
            jobs are booked by Jocelyn in their office, not by whoever is on the
            tools that day, so the account is what jobs are allocated to and what
            the SLA is measured against.
          </p>
        </div>

        <div className="panel">
          <h2>Portal links</h2>
          <p>
            Each link is that account&rsquo;s password — anyone holding it sees
            their jobs. To cut off access, change the Portal token in monday and
            run <a href="/setup">Setup step 5</a> again.
          </p>

          {accounts.length === 0 ? (
            <p className="empty">
              No accounts yet. Run <a href="/setup">Setup steps 3 and 5</a>.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Coordinator</th>
                  <th>Link</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a) => (
                  <tr key={a.token} style={{ opacity: a.active ? 1 : 0.5 }}>
                    <td style={{ fontWeight: 600 }}>
                      {a.name}
                      {!a.active && (
                        <span className="pill p-failed" style={{ marginLeft: 8 }}>
                          Inactive
                        </span>
                      )}
                    </td>
                    <td style={{ color: "var(--mid)" }}>
                      {a.coordinator ?? "—"}
                      {a.mobile && <div className="mono">{a.mobile}</div>}
                    </td>
                    <td className="mono">/j/{a.token.slice(0, 10)}…</td>
                    <td>
                      <a className="act ghost" href={`/j/${a.token}`} target="_blank"
                         style={{ textDecoration: "none", display: "inline-block" }}>
                        Open
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}
