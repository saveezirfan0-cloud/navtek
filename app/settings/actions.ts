"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  authChangePassword,
  logoutAll,
  saveSettings,
  sendTestEmail,
  updateProfile,
  type NotificationSettings,
} from "@/lib/api";
import { SESSION_COOKIE, sessionToken } from "@/lib/auth";

/**
 * Writes for /settings. The session cookie is read here, server side, and
 * the Python half decides what it may do — notification config needs an
 * admin, the profile actions only need to be you. The browser's word for
 * either is never enough.
 */

type Result = { ok: true } | { ok: false; error: string };

function failed(error: unknown): Result {
  return { ok: false, error: error instanceof Error ? error.message : "unknown error" };
}

/** Any signed-in user changing their own password — no admin needed. The
 * Python half verifies the current password before accepting the new one. */
export async function changePasswordAction(input: {
  current_password: string;
  new_password: string;
}): Promise<Result> {
  const session = await sessionToken();
  if (!session) return { ok: false, error: "signed out — reload the page" };
  try {
    await authChangePassword(session, input);
    return { ok: true };
  } catch (error) {
    return failed(error);
  }
}

export async function saveNotificationsAction(
  input: NotificationSettings,
): Promise<Result> {
  const session = await sessionToken();
  if (!session) return { ok: false, error: "signed out — reload the page" };
  try {
    await saveSettings(session, input);
    return { ok: true };
  } catch (error) {
    return failed(error);
  }
}

export async function updateProfileAction(name: string): Promise<Result> {
  const session = await sessionToken();
  if (!session) return { ok: false, error: "signed out — reload the page" };
  try {
    await updateProfile(session, { name });
    return { ok: true };
  } catch (error) {
    return failed(error);
  }
}

/** Ends every session, this one included, then lands on /login. */
export async function signOutEverywhereAction(): Promise<void> {
  const session = await sessionToken();
  if (session) {
    try {
      await logoutAll(session);
    } catch {
      // The cookie still goes; orphaned rows expire on their own.
    }
  }
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  redirect("/login");
}

export async function sendTestEmailAction(): Promise<
  { ok: true; to: string[]; provider?: string } | { ok: false; error: string }
> {
  const session = await sessionToken();
  if (!session) return { ok: false, error: "signed out — reload the page" };
  try {
    const result = await sendTestEmail(session);
    if (!result.sent) {
      return { ok: false, error: result.error ?? "The provider refused the send." };
    }
    return { ok: true, to: result.to, provider: result.provider };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "unknown error",
    };
  }
}
