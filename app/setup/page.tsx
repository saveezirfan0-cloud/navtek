import Nav from "../Nav";
import SetupSteps from "./SetupSteps";

export const dynamic = "force-dynamic";

export default function SetupPage() {
  const configured = Boolean(process.env.SETUP_KEY);
  return (
    <>
      <Nav current="/setup" />
      <div className="admin">
        <div className="head">
          <h1>Setup</h1>
          <p>
            Run these in order. Every step is safe to run twice — nothing is
            renamed, moved or deleted, and columns that already exist are left
            alone.
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
