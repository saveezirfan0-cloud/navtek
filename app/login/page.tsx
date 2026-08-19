import { redirect } from "next/navigation";
import { authState } from "@/lib/api";
import { currentUser, homeFor } from "@/lib/auth";
import LoginForm from "./LoginForm";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const user = await currentUser();
  if (user) redirect(homeFor(user));

  const state = await authState();
  const dbReady = state?.database?.ok === true;
  const firstRun = dbReady && state?.users_exist === false;

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="auth-logo">N</span>
          <div>
            <div className="brand">Navtek</div>
            <div className="auth-title">eOrder &amp; installs</div>
          </div>
        </div>

        {!state ? (
          <div className="warnbox">
            <b>The service isn&rsquo;t responding.</b> Open{" "}
            <a href="/api/py/diag" target="_blank">/api/py/diag</a> — it names
            the missing package or file.
          </div>
        ) : !dbReady ? (
          <div className="warnbox">
            <b>The database isn&rsquo;t connected</b>, and logins live there.{" "}
            {state.database?.detail ?? "Set SUPABASE_URL and SUPABASE_SERVICE_KEY in Vercel, then redeploy."}
            {state.database?.state === "no_tables" && (
              <> Then run <code>supabase/migrations/0002_users.sql</code> in the SQL Editor.</>
            )}
          </div>
        ) : (
          <LoginForm firstRun={firstRun} />
        )}

        <p className="auth-foot">
          Installers with a magic link don&rsquo;t sign in — their link opens
          their jobs directly.
        </p>
      </div>
    </div>
  );
}
