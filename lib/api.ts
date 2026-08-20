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
  /** The install item's own id — the subitem when the order has one per site,
   * the order row itself for orders that predate universal install items. */
  install_id?: string;
  subitem_id?: string | null;
  /** The install item's name, e.g. "GPS Tech — 7 units", when it's a subitem. */
  site?: string | null;
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
  monday_item_id: number | null;
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
  allow_duplicate_files?: boolean;
  /** The monday account's slug, when configured — item ids render as links
   * into the board only when this is set. */
  monday_slug?: string | null;
  log_retention_days?: number;
  sla?: {
    go_live_date: string | null;
    business_days: number;
    notifications_enabled: boolean;
    mode: string;
  };
};

export async function getHealth(): Promise<Health | null> {
  try {
    return await call("/health");
  } catch {
    return null;
  }
}

export type DbState = { ok: boolean; state: string; detail?: string };

/** One webhook delivery from monday, whatever came of it. monday's own
 * automation log shows all of these as Success; this is where a skipped
 * duplicate or a no-file delivery becomes visible. */
export type WebhookRun = {
  monday_item_id: number | null;
  opportunity_id: string | null;
  file_name: string | null;
  outcome: "processed" | "skipped" | "failed";
  reason: string | null;
  status: string | null;
  duration_ms: number | null;
  created_at: string;
};

export type RecentPage = {
  enabled: boolean;
  ingests: Ingest[];
  total: number;
  /** Whole-ledger counts by status, independent of the current filter. */
  counts: { read?: number; check?: number; failed?: number };
  database?: DbState;
};

/** One page of the read ledger. status and q filter server side, so a search
 * covers the whole history — not just the rows that happen to be loaded. */
export async function getRecent(
  opts: { limit?: number; offset?: number; status?: string; q?: string } = {},
): Promise<RecentPage> {
  const params = new URLSearchParams({
    limit: String(opts.limit ?? 50),
    offset: String(opts.offset ?? 0),
  });
  if (opts.status) params.set("status", opts.status);
  if (opts.q) params.set("q", opts.q);
  try {
    return await call(`/recent?${params}`);
  } catch (error) {
    // The request itself failed — say so, rather than reporting it as an
    // unconfigured database, which sends people to check the wrong thing.
    return {
      enabled: false,
      ingests: [],
      total: 0,
      counts: {},
      database: {
        ok: false,
        state: "unreachable",
        detail: error instanceof Error ? error.message : "unknown error",
      },
    };
  }
}

/** Everything recorded about one order: every read (with the full parse) and
 * every webhook delivery. Null only when the request itself failed. */
export async function getOrderDetail(itemId: string): Promise<{
  enabled: boolean;
  ingests: (Ingest & { parsed: Record<string, unknown> })[];
  webhooks: WebhookRun[];
  database?: DbState;
} | null> {
  try {
    return await call(`/order?item_id=${encodeURIComponent(itemId)}`);
  } catch {
    return null;
  }
}

export type WebhookLog = {
  enabled: boolean;
  webhook_log_ready?: boolean;
  total: number;
  webhooks: WebhookRun[];
  database?: DbState;
};

/** One page of the webhook delivery log, newest first. `total` counts the
 * whole (filtered) log, not the page — the Deliveries tab derives its pager
 * from it. outcome and q filter server side. */
export async function getWebhookLog(
  limit: number,
  offset: number,
  opts: { outcome?: string; q?: string } = {},
): Promise<WebhookLog> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (opts.outcome) params.set("outcome", opts.outcome);
  if (opts.q) params.set("q", opts.q);
  try {
    return await call(`/webhooks?${params}`);
  } catch (error) {
    return {
      enabled: false,
      total: 0,
      webhooks: [],
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

/** Change the signed-in user's own password. Throws an ApiError with a
 * human-readable message on a wrong current password, a too-short new one,
 * or a database problem — the form shows it verbatim. */
export async function authChangePassword(
  session: string,
  input: { current_password: string; new_password: string },
): Promise<void> {
  await call("/auth/change-password", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "X-Session": session },
  });
}

export async function authMe(session: string): Promise<AuthUser | null> {
  try {
    const data = await call("/auth/me", { headers: { "X-Session": session } });
    return data.user ?? null;
  } catch {
    return null;
  }
}

// -- activity (admin) --------------------------------------------------------

export type ActivityEvent = {
  action: string;
  monday_item_id: number | null;
  installer_account_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type UnknownReason = {
  order_reason: string;
  opportunity_id: string | null;
  file_name: string | null;
  seen_at: string;
};

export type LedgerEntry = {
  monday_item_id: number;
  kind: string;
  payload: Record<string, unknown>;
  sent_at: string;
};

export type ActivityPage = {
  page_size: number;
  events: ActivityEvent[];
  events_total: number;
  notifications: LedgerEntry[];
  notifications_total: number;
  unknown_order_reasons: UnknownReason[];
  reasons_total: number;
};

/** The audit trail, one page per table — each table pages independently. */
export async function getActivity(
  session: string,
  offsets: { events?: number; notifications?: number; reasons?: number } = {},
): Promise<ActivityPage | null> {
  const params = new URLSearchParams({
    events_offset: String(offsets.events ?? 0),
    notifications_offset: String(offsets.notifications ?? 0),
    reasons_offset: String(offsets.reasons ?? 0),
  });
  try {
    return await call(`/activity?${params}`, { headers: { "X-Session": session } });
  } catch {
    return null;
  }
}

// -- the SLA console (admin) -------------------------------------------------

export type SlaJob = {
  item_id: string;
  customer: string | null;
  account: string;
  state: string;
  dispatched: string;
  clock_start: string;
  sla_age_business_days: number;
  days_left: number;
  status: "breached" | "due_now" | "on_track";
};

export type SlaPreview = {
  mode: "off" | "shadow" | "live";
  go_live: string | null;
  sla_business_days: number;
  notifications_enabled: boolean;
  jobs_checked: number;
  jobs: SlaJob[];
  ledger: LedgerEntry[];
};

/** What the SLA engine sees right now — read only, writes nothing. */
export async function getSlaPreview(session: string): Promise<SlaPreview | null> {
  try {
    return await call("/sla/preview", { headers: { "X-Session": session } });
  } catch {
    return null;
  }
}

export type SweepResult = {
  ok: boolean;
  swept: boolean;
  shadow?: boolean;
  reason?: string;
  go_live?: string;
  jobs_checked?: number;
  breaches?: Array<{ customer?: string; account?: string; actions?: string[] }>;
};

/** Run the daily SLA sweep on demand — same pass the 7am cron makes. In
 * shadow mode it records breaches and logs would-sends; live, it escalates
 * and texts. The caller must have verified the session belongs to an admin. */
export async function runSlaSweep(session: string): Promise<SweepResult> {
  return call("/sla/sweep", { method: "POST", headers: { "X-Session": session } });
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

// -- workspace settings (admin) ----------------------------------------------

export type NotificationSettings = {
  emails: string[];
  notify_check: boolean;
  notify_failed: boolean;
};

export type WorkspaceSettings = {
  notifications: NotificationSettings;
  email: { provider: "resend" | "smtp" | "log"; from: string | null };
};

export async function getSettings(session: string): Promise<WorkspaceSettings | null> {
  try {
    return await call("/settings", { headers: { "X-Session": session } });
  } catch {
    return null;
  }
}

export async function saveSettings(
  session: string,
  notifications: NotificationSettings,
): Promise<{ notifications: NotificationSettings }> {
  return call("/settings", {
    method: "POST",
    body: JSON.stringify({ notifications }),
    headers: { "X-Session": session },
  });
}

export async function sendTestEmail(
  session: string,
): Promise<{ sent: boolean; to: string[]; provider?: string; error?: string }> {
  return call("/settings/test-email", {
    method: "POST",
    body: JSON.stringify({}),
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
