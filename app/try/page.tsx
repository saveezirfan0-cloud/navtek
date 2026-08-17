import Nav from "../Nav";
import Tester from "./Tester";

export default function TryPage() {
  return (
    <>
      <Nav current="/try" />
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
