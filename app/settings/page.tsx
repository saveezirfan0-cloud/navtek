import Nav from "../Nav";
import ThemeSwitcher from "../theme";
import NotificationsForm from "./NotificationsForm";
import PasswordForm from "./PasswordForm";
import { getSettings } from "@/lib/api";
import { requireViewer, sessionToken } from "@/lib/auth";

export const metadata = { title: "Settings · Navtek" };

export const dynamic = "force-dynamic";

/** Workspace settings. Appearance is personal and open to everyone signed
 * in; the notification recipients are workspace-wide and admin-only — the
 * API enforces that again server side. */
export default async function Settings() {
  const { user, realUser, previewing } = await requireViewer();
  const isAdmin = user.is_admin;

  const session = await sessionToken();
  const settings =
    isAdmin && session && !previewing ? await getSettings(session) : null;

  return (
    <>
      <Nav current="/settings" user={user} realUser={realUser} />
      <div className="admin">
        <div className="head">
          <h1>Settings</h1>
          <p>Your preferences, and how this workspace raises the alarm.</p>
        </div>

        <div className="panel">
          <h2>Appearance</h2>
          <p>
            Light, dark, or follow this device. Remembered per browser — it
            only changes what you see.
          </p>
          <ThemeSwitcher />
        </div>

        <div className="panel">
          <h2>Password</h2>
          <p>
            The password you sign in with. Changing it signs out every other
            device straight away.
          </p>
          {previewing ? (
            <p className="empty">
              Hidden while previewing another login — the session is still
              yours, so this form would change <b>your</b> password, not
              theirs. Exit the preview first.
            </p>
          ) : (
            <PasswordForm />
          )}
        </div>

        <div className="panel">
          <h2>Email notifications</h2>
          <p>
            When an eOrder read lands as <b>⚠️ Check</b> or <b>❌ Failed</b>,
            the addresses below are emailed with what went wrong and a link to
            the order.
          </p>

          {!isAdmin ? (
            <p className="empty">
              Only an admin can change who gets notified. Ask a Navtek admin if
              the wrong people are (or aren&rsquo;t) hearing about failures.
            </p>
          ) : previewing ? (
            <p className="empty">
              Hidden while previewing another login — exit the preview to edit
              notification settings.
            </p>
          ) : !settings ? (
            <div className="warnbox">
              <b>Could not load the saved settings.</b> The database may be
              unreachable, or the <code>app_settings</code> table is missing —
              run <code>supabase/migrations/0007_app_settings.sql</code> in the
              Supabase SQL Editor.
            </div>
          ) : (
            <>
              {settings.email.provider === "log" ? (
                <div className="warnbox">
                  <b>No email provider is configured</b> — alerts are written to
                  the server logs instead of sent. Set{" "}
                  <code>RESEND_API_KEY</code> + <code>EMAIL_FROM</code> (or{" "}
                  <code>SMTP_HOST</code>/<code>SMTP_PORT</code>/
                  <code>SMTP_USER</code>/<code>SMTP_PASS</code> +{" "}
                  <code>EMAIL_FROM</code>) in Vercel, then redeploy.
                </div>
              ) : (
                <p className="tiny" style={{ marginBottom: 14 }}>
                  Sending via <b>{settings.email.provider}</b>
                  {settings.email.from && (
                    <>
                      {" "}as <b>{settings.email.from}</b>
                    </>
                  )}
                  .
                </p>
              )}
              <NotificationsForm
                initial={settings.notifications}
                readOnly={false}
              />
            </>
          )}
        </div>
      </div>
    </>
  );
}
