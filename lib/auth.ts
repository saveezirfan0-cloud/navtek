/**
 * Who is signed in, answered server side.
 *
 * The browser holds one opaque token in an httpOnly cookie. Nothing about
 * access lives in the browser — every page asks the Python half what the
 * token means on every request, so cutting someone off on the Users page
 * takes effect on their next click, not their next login.
 */

import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { adminPreviewUser, authMe, type AuthUser } from "./api";

export const SESSION_COOKIE = "navtek_session";
export const PREVIEW_COOKIE = "navtek_preview";

export async function sessionToken(): Promise<string | null> {
  const jar = await cookies();
  return jar.get(SESSION_COOKIE)?.value ?? null;
}

export async function currentUser(): Promise<AuthUser | null> {
  const token = await sessionToken();
  if (!token) return null;
  return authMe(token);
}

/** Signed in, or bounced to /login. Access flags are the page's job to check —
 * a wrong-flag visit gets an explanation, not a redirect loop. */
export async function requireUser(): Promise<AuthUser> {
  const user = await currentUser();
  if (!user) redirect("/login");
  return user;
}

/**
 * The signed-in user, plus who the page should render AS.
 *
 * Normally the same person. When an admin is previewing another login (the
 * Preview button on /users sets an httpOnly cookie with the target's id),
 * `user` becomes that login's access flags so every page and the nav gate
 * exactly as they would for them — while `realUser` stays the admin, whose
 * session authorises everything. The cookie alone is inert: it only takes
 * effect on top of a valid ADMIN session, resolved server side per request,
 * and no session is ever minted for the previewed user.
 */
export type Viewer = { user: AuthUser; realUser: AuthUser; previewing: boolean };

export async function requireViewer(): Promise<Viewer> {
  const real = await requireUser();
  if (real.is_admin) {
    const jar = await cookies();
    const targetId = jar.get(PREVIEW_COOKIE)?.value;
    if (targetId && targetId !== real.id) {
      const token = await sessionToken();
      const target = token ? await adminPreviewUser(token, targetId) : null;
      if (target) return { user: target, realUser: real, previewing: true };
    }
  }
  return { user: real, realUser: real, previewing: false };
}

/** Where a fresh login should land, given what they can see. */
export function homeFor(user: AuthUser): string {
  if (user.is_admin || user.can_orders) return "/";
  if (user.can_installer) return "/portal";
  return "/";
}
