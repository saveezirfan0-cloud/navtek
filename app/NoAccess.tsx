import Link from "next/link";
import type { AuthUser } from "@/lib/api";

/** Shown when someone is signed in but this page isn't switched on for them.
 * An explanation beats a redirect loop — they can see where they CAN go. */
export default function NoAccess({ user, need }: { user: AuthUser; need: string }) {
  return (
    <div className="admin">
      <div className="notice" style={{ maxWidth: 520, marginTop: 48 }}>
        <h2>This page isn&rsquo;t switched on for you</h2>
        <p>
          {need} access is enabled per user by a Navtek admin, on the Users page.
        </p>
        <p style={{ marginTop: 10 }}>
          {user.can_installer && <Link href="/portal">Go to your jobs</Link>}
          {user.can_installer && user.can_orders && " · "}
          {user.can_orders && <Link href="/">Go to Orders</Link>}
        </p>
      </div>
    </div>
  );
}
