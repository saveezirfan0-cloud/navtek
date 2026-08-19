import { getJobs } from "@/lib/api";
import JobCard from "@/app/jobs/JobCard";
import Staleness from "@/app/jobs/Staleness";

export const dynamic = "force-dynamic";

/** The magic-link portal. The link is the password — no sign-in, by design:
 * this is what gets texted to a sole operator in a truck yard. */
export default async function Portal({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const data = await getJobs(token);

  if (!data) {
    return (
      <div className="wrap">
        <div className="notice">
          <h2>This link no longer works</h2>
          <p>
            Ask Navtek to send you a new one — links are reissued when an account
            changes.
          </p>
        </div>
      </div>
    );
  }

  const { account, action_needed, waiting, overdue } = data;
  const total = action_needed.length;

  return (
    <div className="wrap">
      <header>
        <div className="brand">{account.name} · Navtek installs</div>
        <div className="who">{account.coordinator ?? account.name}</div>
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

      <Staleness refreshedAt={data.refreshed_at} stale={data.stale} />

      {action_needed.length > 0 && <div className="sect">Action needed</div>}
      {action_needed.map((job) => (
        <JobCard key={job.item_id} job={job} token={token} />
      ))}

      {waiting.length > 0 && <div className="sect">Waiting on hardware</div>}
      {waiting.map((job) => (
        <JobCard key={job.item_id} job={job} token={token} />
      ))}

      {total === 0 && waiting.length === 0 && (
        <div className="notice">
          <h2>All clear</h2>
          <p>New jobs appear here as soon as Navtek dispatch the hardware.</p>
        </div>
      )}

      <div className="foot">Navtek Australia · installer portal</div>
    </div>
  );
}
