"use server";

import { saveSettings, sendTestEmail, type NotificationSettings } from "@/lib/api";
import { sessionToken } from "@/lib/auth";

/**
 * Admin-only writes for /settings. The session cookie is read here, server
 * side, and the Python half checks it belongs to an admin — the browser's
 * word for it is never enough.
 */

type Result = { ok: true } | { ok: false; error: string };

function failed(error: unknown): Result {
  return { ok: false, error: error instanceof Error ? error.message : "unknown error" };
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
