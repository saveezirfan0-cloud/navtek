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
import { authMe, type AuthUser } from "./api";

export const SESSION_COOKIE = "navtek_session";

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

/** Where a fresh login should land, given what they can see. */
export function homeFor(user: AuthUser): string {
  if (user.is_admin || user.can_orders) return "/";
  if (user.can_installer) return "/portal";
  return "/";
}
