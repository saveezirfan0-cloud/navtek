import Link from "next/link";
import type { AuthUser } from "@/lib/api";
import { signOut } from "./login/actions";

/**
 * Staff navigation. Deliberately not in the root layout — the installer portal
 * (magic-link and logged-in alike) is used by people outside Navtek and must
 * not show links into the board setup.
 *
 * Links follow access: what you can't open, you don't see. The pages enforce
 * it again server side — hiding a link is courtesy, not security.
 */
export default function Nav({ current, user }: { current: string; user: AuthUser }) {
  const links: [string, string][] = [];
  if (user.can_orders) {
    links.push(["/", "Orders"], ["/try", "File tester"]);
  }
  if (user.can_installer || user.installer_account_id) {
    links.push(["/portal", "My jobs"]);
  }
  if (user.is_admin) {
    links.push(["/installers", "Installers"], ["/users", "Users"], ["/setup", "Setup"]);
  }
  return (
    <nav className="nav">
      <div className="inner">
        <span className="mark">Navtek · eOrder</span>
        {links.map(([href, label]) => (
          <Link key={href} href={href} aria-current={href === current ? "page" : undefined}>
            {label}
          </Link>
        ))}
        <span className="nav-user">
          <span className="nav-name" title={user.email}>{user.name}</span>
          <form action={signOut}>
            <button className="nav-out" type="submit">Sign out</button>
          </form>
        </span>
      </div>
    </nav>
  );
}
