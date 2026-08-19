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
    throw new Error(data?.detail ?? `service returned ${response.status}`);
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
};

export async function getJobs(token: string): Promise<JobsResponse | null> {
  try {
    return await call(`/portal/jobs?token=${encodeURIComponent(token)}`);
  } catch {
    return null;
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
    return await call("/recent");
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
