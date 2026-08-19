import Nav from "../Nav";
import NoAccess from "../NoAccess";
import Tester from "./Tester";
import { requireViewer } from "@/lib/auth";

export const metadata = { title: "File tester · Navtek" };

export const dynamic = "force-dynamic";

export default async function TryPage() {
  const { user, realUser } = await requireViewer();
  if (!user.can_orders && !user.is_admin) {
    return (
      <>
        <Nav current="/try" user={user} realUser={realUser} />
        <NoAccess user={user} need="Orders" />
      </>
    );
  }
  return (
    <>
      <Nav current="/try" user={user} realUser={realUser} />
      <div className="admin">
        <div className="head">
          <h1>File tester</h1>
          <p>
            Drop a Teletrac Navman eOrder here to see exactly what the parser
            reads out of it. Nothing is written to monday or the database, so
            this is safe to use on anything, any time a file looks wrong.
          </p>
        </div>
        <div className="panel">
          <Tester />
        </div>
      </div>
    </>
  );
}
