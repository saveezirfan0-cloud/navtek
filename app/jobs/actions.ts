"use server";

import { cookies } from "next/headers";
import { postAction, postMyAction } from "@/lib/api";
import { SESSION_COOKIE } from "@/lib/auth";

/**
 * One write-back for both ways into the portal. A magic link carries its
 * token; a logged-in installer carries nothing — their session cookie is read
 * here, server side, and the Python half checks it maps to an installer
 * account. Either way the shared secret is added on this side and the browser
 * never holds it.
 */
export async function submitJob(input: {
  token?: string;
  item_id: string;
  action: "contacted" | "booked" | "progress" | "completed" | "blocked";
  value?: string | number;
}): Promise<{ ok: true } | { ok: false; error: string }> {
  try {
    const { token, ...rest } = input;
    if (token) {
      await postAction({ token, ...rest });
    } else {
      const jar = await cookies();
      const session = jar.get(SESSION_COOKIE)?.value;
      if (!session) return { ok: false, error: "signed out — reload the page" };
      await postMyAction(session, rest);
    }
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "unknown error" };
  }
}
