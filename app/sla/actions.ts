"use server";

import { revalidatePath } from "next/cache";
import { authMe, runSlaSweep, type SweepResult } from "@/lib/api";
import { sessionToken } from "@/lib/auth";

/**
 * Run the SLA sweep from the console — the same pass the 7am cron makes,
 * for whoever can't (or shouldn't have to) curl an endpoint with a secret.
 *
 * The Python half authorises the call with the portal shared secret, which
 * only this server holds; the admin check happens here, against the session,
 * server side — the browser's word for it is never enough.
 */
export async function runSweepAction(): Promise<
  { ok: true; result: SweepResult } | { ok: false; error: string }
> {
  const session = await sessionToken();
  if (!session) return { ok: false, error: "signed out — reload the page" };
  const me = await authMe(session);
  if (!me?.is_admin) return { ok: false, error: "Only an admin can run the sweep." };
  try {
    const result = await runSlaSweep(session);
    revalidatePath("/sla");
    return { ok: true, result };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "the sweep failed",
    };
  }
}
