"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { signOut } from "./login/actions";
import ThemeSwitcher from "./theme";

/**
 * The app shell's chrome: a fixed sidebar of modules on a desk, a top bar
 * with a drawer on a phone, and the profile menu (theme, settings, sign out)
 * at the bottom rail. Server-side concerns stay out: Nav.tsx decides WHICH
 * links this login gets; this component only draws and folds them.
 */

export type NavLink = { href: string; label: string; icon: string };
export type NavGroup = { label: string; links: NavLink[] };

function Icon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    orders: (
      <>
        <path d="M4 4h12v14H4z" />
        <path d="M7 8h6M7 11h6M7 14h4" />
      </>
    ),
    deliveries: (
      <>
        <path d="M2 5h9v8H2zM11 8h4l3 3v2h-7z" />
        <circle cx="5.5" cy="15" r="1.6" />
        <circle cx="14.5" cy="15" r="1.6" />
      </>
    ),
    tester: (
      <>
        <path d="M8 3h4M9 3v5l-4.5 7a2 2 0 0 0 1.7 3h7.6a2 2 0 0 0 1.7-3L11 8V3" />
      </>
    ),
    jobs: (
      <>
        <path d="M3 7h14v10H3z" />
        <path d="M7 7V5a3 3 0 0 1 6 0v2" />
      </>
    ),
    installers: (
      <>
        <circle cx="7" cy="7" r="2.6" />
        <path d="M2.5 16a4.5 4.5 0 0 1 9 0" />
        <circle cx="14" cy="8" r="2.2" />
        <path d="M12.5 16a4 4 0 0 1 5 -3.4" />
      </>
    ),
    sla: (
      <>
        <circle cx="10" cy="11" r="6.5" />
        <path d="M10 7.5V11l2.5 1.8M7.5 2.5h5" />
      </>
    ),
    activity: <path d="M2 11h4l2-6 4 12 2-6h4" />,
    users: (
      <>
        <circle cx="10" cy="6.5" r="3" />
        <path d="M4 17a6 6 0 0 1 12 0" />
      </>
    ),
    setup: (
      <>
        <circle cx="10" cy="10" r="2.5" />
        <path d="M10 3v2.2M10 14.8V17M3 10h2.2M14.8 10H17M5.1 5.1l1.5 1.5M13.4 13.4l1.5 1.5M14.9 5.1l-1.5 1.5M6.6 13.4l-1.5 1.5" />
      </>
    ),
    settings: (
      <>
        <path d="M3 6h14M3 14h14" />
        <circle cx="8" cy="6" r="1.8" />
        <circle cx="12.5" cy="14" r="1.8" />
      </>
    ),
  };
  return (
    <svg
      className="side-ico"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] ?? <circle cx="10" cy="10" r="6" />}
    </svg>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export default function Sidebar({
  current,
  groups,
  name,
  email,
  isAdmin,
}: {
  current: string;
  groups: NavGroup[];
  name: string;
  email: string;
  isAdmin: boolean;
}) {
  const [open, setOpen] = useState(false); // the phone drawer
  const [menu, setMenu] = useState(false); // the profile menu
  const menuRef = useRef<HTMLDivElement>(null);

  // Following a link closes the drawer and the menu; so does a click outside
  // the menu or the Escape key — small things, but they are the difference
  // between chrome that feels engineered and chrome that feels stuck on.
  useEffect(() => {
    if (!menu) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  const closeAll = () => {
    setOpen(false);
    setMenu(false);
  };

  return (
    <>
      <div className="topbar">
        <button
          className="burger"
          type="button"
          aria-label={open ? "Close the menu" : "Open the menu"}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" aria-hidden="true">
            {open ? <path d="M5 5l10 10M15 5L5 15" /> : <path d="M3 6h14M3 10h14M3 14h14" />}
          </svg>
        </button>
        <span className="topbar-brand">
          <span className="side-logo" aria-hidden="true">N</span> Navtek
        </span>
      </div>
      {open && <div className="scrim" onClick={closeAll} aria-hidden="true" />}

      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="side-brand">
          <span className="side-logo" aria-hidden="true">N</span>
          <span>
            <span className="side-name">Navtek</span>
            <span className="side-sub">eOrder workspace</span>
          </span>
        </div>

        <nav className="side-nav" aria-label="Main">
          {groups.map((group) => (
            <div className="side-group" key={group.label}>
              <div className="side-label">{group.label}</div>
              {group.links.map((link) => (
                <Link
                  key={link.href}
                  className="side-link"
                  href={link.href}
                  aria-current={link.href === current ? "page" : undefined}
                  onClick={closeAll}
                >
                  <Icon name={link.icon} />
                  <span>{link.label}</span>
                </Link>
              ))}
            </div>
          ))}
        </nav>

        <div className="side-foot" ref={menuRef}>
          {menu && (
            <div className="profile-menu" role="menu">
              <div className="pm-who">
                <div className="pm-name">{name}</div>
                <div className="pm-email">{email}</div>
                {isAdmin && <span className="pm-role">Admin</span>}
              </div>
              <div className="pm-sect">Appearance</div>
              <div className="pm-row">
                <ThemeSwitcher compact />
              </div>
              <div className="pm-split" />
              <Link className="pm-item" href="/settings" role="menuitem" onClick={closeAll}>
                Settings
              </Link>
              <form action={signOut}>
                <button className="pm-item pm-out" type="submit" role="menuitem">
                  Sign out
                </button>
              </form>
            </div>
          )}
          <button
            className="profile-btn"
            type="button"
            aria-haspopup="menu"
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
          >
            <span className="avatar" aria-hidden="true">{initials(name)}</span>
            <span className="profile-meta">
              <span className="profile-name">{name}</span>
              <span className="profile-email">{email}</span>
            </span>
            <svg className="chev" viewBox="0 0 20 20" fill="none" stroke="currentColor"
                 strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
                 aria-hidden="true">
              <path d="M6 12.5l4-4 4 4" />
            </svg>
          </button>
        </div>
      </aside>
    </>
  );
}
