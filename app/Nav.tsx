import Link from "next/link";

/**
 * Admin navigation. Deliberately not in the root layout — the installer portal
 * at /j/[token] is opened by people outside Navtek and must not show links
 * into the board setup.
 */
export default function Nav({ current }: { current: string }) {
  const links = [
    ["/", "Orders"],
    ["/installers", "Installers"],
    ["/try", "File tester"],
    ["/setup", "Setup"],
  ];
  return (
    <nav className="nav">
      <div className="inner">
        <span className="mark">Navtek · eOrder</span>
        {links.map(([href, label]) => (
          <Link key={href} href={href} aria-current={href === current ? "page" : undefined}>
            {label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
