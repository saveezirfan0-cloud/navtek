import type { AuthUser } from "@/lib/api";
import { stopPreviewAction } from "./users/actions";
import Sidebar, { type NavGroup } from "./Sidebar";

/**
 * Staff navigation — the app shell's sidebar. Deliberately not in the root
 * layout: the installer portal (magic-link and logged-in alike) is used by
 * people outside Navtek and must not show links into the board setup.
 *
 * Links follow access: what you can't open, you don't see. The pages enforce
 * it again server side — hiding a link is courtesy, not security. This file
 * decides WHICH modules a login gets; Sidebar.tsx draws them.
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
  const groups: NavGroup[] = [];

  if (user.can_orders || user.is_admin) {
    groups.push({
      label: "Operations",
      links: [
        { href: "/", label: "Orders", icon: "orders" },
        { href: "/deliveries", label: "Deliveries", icon: "deliveries" },
        { href: "/try", label: "File tester", icon: "tester" },
      ],
    });
  }

  const fieldLinks: NavGroup["links"] = [];
  // The Installer ACCESS switch decides this — a linked account alone is not
  // access. (An admin sees it too once linked, since the page lets them in.)
  if (user.can_installer || (user.is_admin && user.installer_account_id)) {
    fieldLinks.push({ href: "/portal", label: "My jobs", icon: "jobs" });
  }
  if (user.is_admin) {
    fieldLinks.push(
      { href: "/installers", label: "Installers", icon: "installers" },
      { href: "/sla", label: "SLA console", icon: "sla" },
    );
  }
  if (fieldLinks.length > 0) groups.push({ label: "Field", links: fieldLinks });

  if (user.is_admin) {
    groups.push({
      label: "Administration",
      links: [
        { href: "/activity", label: "Activity", icon: "activity" },
        { href: "/users", label: "Users", icon: "users" },
        { href: "/setup", label: "Board setup", icon: "setup" },
      ],
    });
  }

  // Everyone signed in gets Settings — appearance is personal; the
  // notification recipients inside it are gated to admins by the page.
  groups.push({
    label: "Workspace",
    links: [{ href: "/settings", label: "Settings", icon: "settings" }],
  });

  const who = realUser ?? user;
  return (
    <>
      <Sidebar
        current={current}
        groups={groups}
        name={who.name}
        email={who.email}
        isAdmin={who.is_admin}
      />
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
