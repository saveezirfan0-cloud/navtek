"use server";

import { postAction } from "@/lib/api";

/**
 * Server action wrapper. The token arrives from the URL the installer already
 * holds; the shared secret is added here, server side, and never sent to the
 * browser.
 */
export async function submit(input: {
  token: string;
  item_id: string;
  action: "contacted" | "booked" | "progress" | "completed" | "blocked";
  value?: string | number;
}): Promise<{ ok: true } | { ok: false; error: string }> {
  try {
    await postAction(input);
    return { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "unknown error" };
  }
}
