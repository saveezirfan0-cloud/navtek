import Nav from "../Nav";
import NoAccess from "../NoAccess";
import Tester from "./Tester";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function TryPage() {
  const user = await requireUser();
  if (!user.can_orders) {
    return (
      <>
        <Nav current="/try" user={user} />
        <NoAccess user={user} need="Orders" />
      </>
    );
  }
  return (
    <>
      <Nav current="/try" user={user} />
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
