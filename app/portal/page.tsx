import Link from "next/link";
import AutoRefresh from "@/app/AutoRefresh";
import { getMyJobs } from "@/lib/api";
import { requireUser, sessionToken } from "@/lib/auth";
import JobCard from "@/app/jobs/JobCard";
import { signOut } from "@/app/login/actions";

export const dynamic = "force-dynamic";

/** The installer portal for someone with a login — same cards, same actions
 * as the magic-link portal, scoped server side to the ONE installer account
 * their user record is linked to. */
export default async function MyJobs() {
  const user = await requireUser();

  if (!user.can_installer && !user.is_admin) {
    return (
      <div className="wrap">
        <div className="notice">
          <h2>No installer access</h2>
          <p>
            This login doesn&rsquo;t have the installer portal switched on. Ask a
            Navtek admin to enable it on the Users page.
            {user.can_orders && (
              <>
                {" "}Or head back to the <Link href="/">Orders dashboard</Link>.
              </>
            )}
          </p>
        </div>
      </div>
    );
  }

  const session = await sessionToken();
  const data = session ? await getMyJobs(session) : null;

  if (!data) {
    return (
      <div className="wrap">
        <div className="notice">
          <h2>No installer account linked</h2>
          <p>
            This login isn&rsquo;t linked to an installer account yet, so there
            are no jobs to show. A Navtek admin can link one on the Users page.
          </p>
        </div>
      </div>
    );
  }

  const { account, action_needed, waiting, overdue } = data;
  const total = action_needed.length;

  return (
    <div className="wrap">
      <AutoRefresh seconds={60} />
      <header>
        <div className="brand">{account.name} · Navtek installs</div>
        <div className="who">{user.name}</div>
        <div className="summary">
          {total === 0 ? (
            "Nothing needs your attention right now."
          ) : (
            <>
              {total} job{total === 1 ? "" : "s"} need your attention
              {overdue > 0 && (
                <>
                  {" — "}
                  <span className="hot">{overdue} past the 2-day SLA</span>
                </>
              )}
              .
            </>
          )}
        </div>
      </header>

      {action_needed.length > 0 && <div className="sect">Action needed</div>}
      {action_needed.map((job) => (
        <JobCard key={job.item_id} job={job} />
      ))}

      {waiting.length > 0 && <div className="sect">Waiting on hardware</div>}
      {waiting.map((job) => (
        <JobCard key={job.item_id} job={job} />
      ))}

      {total === 0 && waiting.length === 0 && (
        <div className="notice">
          <h2>All clear</h2>
          <p>New jobs appear here as soon as Navtek dispatch the hardware.</p>
        </div>
      )}

      <div className="foot">
        Signed in as {user.email}
        {" · "}
        <form action={signOut} style={{ display: "inline" }}>
          <button className="linklike" type="submit">Sign out</button>
        </form>
        <br />
        Navtek Australia · installer portal
      </div>
    </div>
  );
}
