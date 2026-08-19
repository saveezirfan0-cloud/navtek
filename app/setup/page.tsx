import Nav from "../Nav";
import NoAccess from "../NoAccess";
import SetupSteps from "./SetupSteps";
import { requireViewer } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function SetupPage() {
  const { user, realUser } = await requireViewer();
  if (!user.is_admin) {
    return (
      <>
        <Nav current="/setup" user={user} realUser={realUser} />
        <NoAccess user={user} need="Admin" />
      </>
    );
  }

  const configured = Boolean(process.env.SETUP_KEY);
  return (
    <>
      <Nav current="/setup" user={user} realUser={realUser} />
      <div className="admin">
        <div className="head">
          <h1>Setup</h1>
          <p>
            Run these in order. Every step is safe to run twice — nothing is
            renamed, moved or deleted, and columns that already exist are left
            alone.
          </p>
        </div>
        <div className="panel" style={{ paddingTop: 14, paddingBottom: 14 }}>
          <p style={{ margin: 0, fontSize: 14.5, color: "var(--mid)" }}>
            Buttons returning <b>HTTP 500</b> with nothing else?{" "}
            <a href="/api/py/diag" target="_blank">Run the diagnostic</a> — it is
            a separate function that still answers when this one cannot start,
            and it names the cause.
          </p>
        </div>
        {configured ? (
          <SetupSteps />
        ) : (
          <div className="panel">
            <div className="warnbox">
              <b>SETUP_KEY isn&rsquo;t set.</b> Add it in the Vercel project
              settings under Environment Variables, then redeploy. This page
              creates columns on the live TN Orders board, so it stays locked
              until you do.
            </div>
          </div>
        )}
      </div>
    </>
  );
}
