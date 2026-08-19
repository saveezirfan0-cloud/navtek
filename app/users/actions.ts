"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { adminCreateUser, adminPreviewUser, adminUpdateUser } from "@/lib/api";
import { homeFor, PREVIEW_COOKIE, sessionToken } from "@/lib/auth";

/**
 * Admin-only writes. The session cookie is read here, server side, and the
 * Python half checks it belongs to an admin — the browser's word for it is
 * never enough.
 */

type Result = { ok: true } | { ok: false; error: string };

function failed(error: unknown): Result {
  return { ok: false, error: error instanceof Error ? error.message : "unknown error" };
}

export async function createUserAction(input: {
  email: string;
  name: string;
  password: string;
  is_admin?: boolean;
  can_orders?: boolean;
  can_installer?: boolean;
  installer_account_id?: string | null;
}): Promise<Result> {
  const session = await sessionToken();
  if (!session) return { ok: false, error: "signed out — reload the page" };
  try {
    await adminCreateUser(session, input);
    return { ok: true };
  } catch (error) {
    return failed(error);
  }
}

/**
 * See the app as another login sees it. Sets an httpOnly cookie with the
 * target's id — inert on its own: lib/auth.ts only honours it on top of a
 * valid ADMIN session, resolved server side on every request, and no session
 * is ever minted for the previewed user. Writes stay disabled while previewing.
 */
export async function startPreviewAction(userId: string): Promise<Result | void> {
  const session = await sessionToken();
  if (!session) return { ok: false, error: "signed out — reload the page" };
  const target = await adminPreviewUser(session, userId);
  if (!target) return { ok: false, error: "couldn't load that user" };
  const jar = await cookies();
  jar.set(PREVIEW_COOKIE, userId, {
    httpOnly: true, sameSite: "lax", secure: true, path: "/",
    maxAge: 60 * 30, // a preview is a look around, not a mode to live in
  });
  redirect(homeFor(target));
}

export async function stopPreviewAction(): Promise<void> {
  const jar = await cookies();
  jar.delete(PREVIEW_COOKIE);
  redirect("/users");
}

export async function updateUserAction(input: {
  id: string;
  is_admin?: boolean;
  can_orders?: boolean;
  can_installer?: boolean;
  active?: boolean;
  installer_account_id?: string | null;
  password?: string;
}): Promise<Result> {
  const session = await sessionToken();
  if (!session) return { ok: false, error: "signed out — reload the page" };
  try {
    await adminUpdateUser(session, input);
    return { ok: true };
  } catch (error) {
    return failed(error);
  }
}
