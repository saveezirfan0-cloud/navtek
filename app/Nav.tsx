import Link from "next/link";
import type { AuthUser } from "@/lib/api";
import { signOut } from "./login/actions";
import { stopPreviewAction } from "./users/actions";

/**
 * Staff navigation. Deliberately not in the root layout — the installer portal
 * (magic-link and logged-in alike) is used by people outside Navtek and must
 * not show links into the board setup.
 *
 * Links follow access: what you can't open, you don't see. The pages enforce
 * it again server side — hiding a link is courtesy, not security.
 */
export default function Nav({
  current,
  user,
  realUser,
}: {
  current: string;
  user: AuthUser;
  /** Set while an admin is previewing: the admin behind the session. */
  realUser?: AuthUser;
}) {
  const previewing = Boolean(realUser && realUser.id !== user.id);
  const links: [string, string][] = [];
  if (user.can_orders || user.is_admin) {
    links.push(["/", "Orders"], ["/deliveries", "Deliveries"], ["/try", "File tester"]);
  }
  // The Installer ACCESS switch decides this — a linked account alone is not
  // access. (An admin sees it too once linked, since the page lets them in.)
  if (user.can_installer || (user.is_admin && user.installer_account_id)) {
    links.push(["/portal", "My jobs"]);
  }
  if (user.is_admin) {
    links.push(["/installers", "Installers"], ["/users", "Users"],
               ["/activity", "Activity"], ["/setup", "Setup"]);
  }
  return (
    <>
      <nav className="nav">
        <div className="inner">
          <span className="mark">Navtek · eOrder</span>
          {links.map(([href, label]) => (
            <Link key={href} href={href} aria-current={href === current ? "page" : undefined}>
              {label}
            </Link>
          ))}
          <span className="nav-user">
            <span className="nav-name" title={(realUser ?? user).email}>
              {(realUser ?? user).name}
            </span>
            <form action={signOut}>
              <button className="nav-out" type="submit">Sign out</button>
            </form>
          </span>
        </div>
      </nav>
      {previewing && (
        <div className="preview-bar">
          <span>
            👁 Previewing as <b>{user.name}</b> — this is what their login sees.
            Actions are disabled.
          </span>
          <form action={stopPreviewAction}>
            <button className="preview-exit" type="submit">Exit preview</button>
          </form>
        </div>
      )}
    </>
  );
}
