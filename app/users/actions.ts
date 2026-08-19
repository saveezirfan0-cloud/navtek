"use server";

import { adminCreateUser, adminUpdateUser } from "@/lib/api";
import { sessionToken } from "@/lib/auth";

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
