/**
 * Server-side client for the Python API.
 *
 * The Python half runs as a Vercel function in /api at the repo root and owns
 * every credential — the monday token reaches the commission columns on the
 * orders board, so it stays there. Everything in this file is server-only:
 * imported by server components and server actions, never by a "use client"
 * file.
 *
 * Do not replace these calls with route handlers under app/api. A project with
 * Python functions in root /api routes the whole /api prefix to them, and
 * app/api handlers stop resolving.
 */

import "server-only";

const SECRET = process.env.PORTAL_SHARED_SECRET ?? "";
const SETUP_KEY = process.env.SETUP_KEY ?? "";

/** Absolute base URL. Same deployment, but fetch still needs a full URL. */
function base() {
  if (process.env.APP_URL) return process.env.APP_URL.replace(/\/$/, "");
  if (process.env.VERCEL_PROJECT_PRODUCTION_URL)
    return `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`;
  if (process.env.VERCEL_URL) return `https://${process.env.VERCEL_URL}`;
  return "http://127.0.0.1:3000";
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function call(path: string, init: RequestInit = {}) {
  const response = await fetch(`${base()}/api/py${path}`, {
    ...init,
    headers: {
      "X-Portal-Secret": SECRET,
      "X-Setup-Key": SETUP_KEY,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
    cache: "no-store",
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      data?.detail ?? `service returned ${response.status}`,
      response.status,
    );
  }
  return data;
}

// -- portal ----------------------------------------------------------------

export type Job = {
  item_id: string;
  name: string;
  customer: string;
  site_contact: string | null;
  site_phone: string | null;
  site_address: string | null;
  opportunity_id: string | null;
  dispatched: string | null;
  contacted: string | null;
  booked: string | null;
  scheduled: string | null;
  units_total: number | null;
  units_installed: number;
  state: "new" | "contacted" | "booked" | "waiting";
  overdue_days: number | null;
  show_counter: boolean;
};

export type JobsResponse = {
  account: { name: string; coordinator: string | null };
  action_needed: Job[];
  waiting: Job[];
  overdue: number;
  sla_days?: number;
  /** When this list was last read from monday (ISO). Null when even the
   * cache is empty. */
  refreshed_at?: string | null;
  /** True when the list came from a cache more than an hour old — the page
   * shows "Updated 3h ago" so nobody drives to a reallocated site. */
  stale?: boolean;
};

/** `gone` is only true when the service itself said the link is unknown — a
 * timeout or a 500 must NOT tell an installer their link is dead. */
export async function getJobs(
  token: string,
): Promise<{ jobs: JobsResponse | null; gone: boolean }> {
  try {
    return { jobs: await call(`/portal/jobs?token=${encodeURIComponent(token)}`), gone: false };
  } catch (error) {
    return { jobs: null, gone: error instanceof ApiError && error.status === 404 };
  }
}

export async function postAction(input: {
  token: string;
  item_id: string;
  action: "contacted" | "booked" | "progress" | "completed" | "blocked";
  value?: string | number;
  note?: string;
}) {
  return call("/portal/action", { method: "POST", body: JSON.stringify(input) });
}

// -- dashboard -------------------------------------------------------------

export type Ingest = {
  opportunity_id: string | null;
  file_name: string | null;
  status: "read" | "check" | "failed";
  warnings: string[];
  changed_fields: string[];
  error: string | null;
  duration_ms: number | null;
  created_at: string;
  item_name: string | null;
};

export type Health = {
  build?: { version: string; commit: string | null };
  ok: boolean;
  missing_secrets: string[];
  config_warnings?: string[];
  unmapped_columns: string[];
  unmapped_optional?: string[];
  orders_board: number;
  write_order_type: boolean;
};

export async function getHealth(): Promise<Health | null> {
  try {
    return await call("/health");
  } catch {
    return null;
  }
}

export type DbState = { ok: boolean; state: string; detail?: string };

export async function getRecent(): Promise<{
  enabled: boolean;
  ingests: Ingest[];
  database?: DbState;
}> {
  try {
    return await call("/recent?limit=50");
  } catch (error) {
    // The request itself failed — say so, rather than reporting it as an
    // unconfigured database, which sends people to check the wrong thing.
    return {
      enabled: false,
      ingests: [],
      database: {
        ok: false,
        state: "unreachable",
        detail: error instanceof Error ? error.message : "unknown error",
      },
    };
  }
}

export type Account = {
  name: string;
  coordinator: string | null;
  mobile: string | null;
  token: string;
  active: boolean;
};

export async function getInstallers(): Promise<{ accounts: Account[] }> {
  try {
    return await call("/installers");
  } catch {
    return { accounts: [] };
  }
}

// -- auth ------------------------------------------------------------------
//
// The browser holds one opaque session token in an httpOnly cookie. Every
// question about who that is goes through here, server side, with the shared
// secret attached — the Python half answers from the database.

export type AuthUser = {
  id: string;
  email: string;
  name: string;
  is_admin: boolean;
  can_orders: boolean;
  can_installer: boolean;
  installer_account_id: string | null;
  active: boolean;
  created_at?: string;
  last_login_at?: string | null;
};

export type AuthState = {
  users_exist: boolean | null;
  database: DbState;
};

export async function authState(): Promise<AuthState | null> {
  try {
    return await call("/auth/state");
  } catch {
    return null;
  }
}

export async function authLogin(input: {
  email: string;
  password: string;
  user_agent?: string;
}): Promise<{ token: string; user: AuthUser }> {
  return call("/auth/login", { method: "POST", body: JSON.stringify(input) });
}

export async function authBootstrap(input: {
  email: string;
  name: string;
  password: string;
  setup_key: string;
  user_agent?: string;
}): Promise<{ token: string; user: AuthUser }> {
  // The typed key replaces the one this server holds: creating the first
  // admin must prove knowledge of SETUP_KEY, not just reach this page.
  const { setup_key, ...body } = input;
  return call("/auth/bootstrap", {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "X-Setup-Key": setup_key },
  });
}

export async function authLogout(token: string): Promise<void> {
  try {
    await call("/auth/logout", { method: "POST", body: JSON.stringify({ token }) });
  } catch {
    // A failed logout still clears the cookie; the session expires on its own.
  }
}

export async function authMe(session: string): Promise<AuthUser | null> {
  try {
    const data = await call("/auth/me", { headers: { "X-Session": session } });
    return data.user ?? null;
  } catch {
    return null;
  }
}

// -- user management (admin) -----------------------------------------------

export type InstallerAccountRef = { id: string; name: string; active: boolean };

export async function adminListUsers(
  session: string,
): Promise<{ users: AuthUser[]; installer_accounts: InstallerAccountRef[] } | null> {
  try {
    return await call("/users", { headers: { "X-Session": session } });
  } catch {
    return null;
  }
}

export async function adminCreateUser(
  session: string,
  input: {
    email: string;
    name: string;
    password: string;
    is_admin?: boolean;
    can_orders?: boolean;
    can_installer?: boolean;
    installer_account_id?: string | null;
  },
): Promise<{ user: AuthUser }> {
  return call("/users", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "X-Session": session },
  });
}

export async function adminUpdateUser(
  session: string,
  input: {
    id: string;
    is_admin?: boolean;
    can_orders?: boolean;
    can_installer?: boolean;
    active?: boolean;
    installer_account_id?: string | null;
    name?: string;
    password?: string;
  },
): Promise<{ user: AuthUser }> {
  return call("/users/update", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "X-Session": session },
  });
}

// -- previewing a user (admin) -----------------------------------------------

/** The AuthUser a given login resolves to — admin session required. Used to
 * render the app through that user's eyes without minting them a session. */
export async function adminPreviewUser(
  session: string,
  userId: string,
): Promise<AuthUser | null> {
  try {
    const data = await call(`/users/preview?user_id=${encodeURIComponent(userId)}`, {
      headers: { "X-Session": session },
    });
    return data.user ?? null;
  } catch {
    return null;
  }
}

/** The job list a given installer login would see — admin session required,
 * read only (no 'viewed' event is recorded server side). */
export async function getPreviewJobs(
  session: string,
  userId: string,
): Promise<JobsResponse | null> {
  try {
    return await call(`/portal/preview-jobs?user_id=${encodeURIComponent(userId)}`, {
      headers: { "X-Session": session },
    });
  } catch {
    return null;
  }
}

// -- the portal, for logged-in installer users ------------------------------

export async function getMyJobs(session: string): Promise<JobsResponse | null> {
  try {
    return await call("/portal/my-jobs", { headers: { "X-Session": session } });
  } catch {
    return null;
  }
}

export async function postMyAction(
  session: string,
  input: {
    item_id: string;
    action: "contacted" | "booked" | "progress" | "completed" | "blocked";
    value?: string | number;
    note?: string;
  },
) {
  return call("/portal/my-action", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "X-Session": session },
  });
}
