import Nav from "../Nav";
import NoAccess from "../NoAccess";
import UsersAdmin from "./UsersAdmin";
import { adminListUsers } from "@/lib/api";
import { requireUser, sessionToken } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function UsersPage() {
  const user = await requireUser();
  if (!user.is_admin) {
    return (
      <>
        <Nav current="/users" user={user} />
        <NoAccess user={user} need="Admin" />
      </>
    );
  }

  const session = await sessionToken();
  const data = session ? await adminListUsers(session) : null;

  return (
    <>
      <Nav current="/users" user={user} />
      <div className="admin">
        <div className="head">
          <h1>Users</h1>
          <p>
            Who can sign in, and what each login can see. <b>Orders</b> is the
            dashboard and file tester; <b>Installer</b> is the portal, and needs
            an installer account linked so the login only ever sees that
            account&rsquo;s jobs. Admins see everything, including this page.
          </p>
        </div>
        {!data ? (
          <div className="panel">
            <div className="warnbox">
              <b>Couldn&rsquo;t load users.</b> The database may not be
              connected, or <code>supabase/migrations/0002_users.sql</code>{" "}
              hasn&rsquo;t been run yet.
            </div>
          </div>
        ) : (
          <UsersAdmin
            me={user}
            users={data.users}
            accounts={data.installer_accounts}
          />
        )}
      </div>
    </>
  );
}
