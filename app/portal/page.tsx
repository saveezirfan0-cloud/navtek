import Link from "next/link";
import AutoRefresh from "@/app/AutoRefresh";
import { getMyJobs, getPreviewJobs } from "@/lib/api";
import { requireViewer, sessionToken } from "@/lib/auth";
import JobCard from "@/app/jobs/JobCard";
import { signOut } from "@/app/login/actions";
import { stopPreviewAction } from "@/app/users/actions";

export const dynamic = "force-dynamic";

/** The installer portal for someone with a login — same cards, same actions
 * as the magic-link portal, scoped server side to the ONE installer account
 * their user record is linked to. An admin previewing another login sees the
 * same page for THAT login's account, read-only. */
export default async function MyJobs() {
  const { user, previewing } = await requireViewer();

  const exitPreview = previewing && (
    <div className="preview-bar">
      <span>👁 Previewing as <b>{user.name}</b></span>
      <form action={stopPreviewAction}>
        <button className="preview-exit" type="submit">Exit preview</button>
      </form>
    </div>
  );

  if (!user.can_installer && !user.is_admin) {
    return (
      <div className="wrap">
        {exitPreview}
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
  const data = session
    ? previewing
      ? await getPreviewJobs(session, user.id)   // the TARGET's account, read-only
      : await getMyJobs(session)
    : null;

  if (!data) {
    return (
      <div className="wrap">
        {exitPreview}
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
      {previewing && (
        <div className="preview-bar">
          <span>
            👁 Previewing as <b>{user.name}</b> — {account.name}&rsquo;s jobs,
            read-only.
          </span>
          <form action={stopPreviewAction}>
            <button className="preview-exit" type="submit">Exit preview</button>
          </form>
        </div>
      )}
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
        <JobCard key={job.install_id ?? job.item_id} job={job} readOnly={previewing} />
      ))}

      {waiting.length > 0 && <div className="sect">Waiting on hardware</div>}
      {waiting.map((job) => (
        <JobCard key={job.install_id ?? job.item_id} job={job} readOnly={previewing} />
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
