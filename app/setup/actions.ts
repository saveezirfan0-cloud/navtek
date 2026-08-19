"use server";

/**
 * Server actions for the setup page.
 *
 * The setup key is an environment variable read here, server-side. The page
 * itself never receives it — a browser holding a key that creates columns on a
 * live monday board is not a thing worth having.
 */

const BASE = () => {
  if (process.env.APP_URL) return process.env.APP_URL.replace(/\/$/, "");
  if (process.env.VERCEL_PROJECT_PRODUCTION_URL)
    return `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`;
  if (process.env.VERCEL_URL) return `https://${process.env.VERCEL_URL}`;
  return "http://127.0.0.1:3000";
};

export type Result = { ok: true; data: unknown } | { ok: false; error: string };

export async function runStep(
  step: "plan" | "columns" | "installers" | "env" | "sync" | "webhook" | "selftest",
  body?: Record<string, unknown>,
): Promise<Result> {
  const method = ["plan", "env", "selftest"].includes(step) ? "GET" : "POST";
  // selftest is not a setup mutation; it lives at the top level.
  const path = step === "selftest" ? "/api/py/selftest" : `/api/py/setup/${step}`;
  try {
    const response = await fetch(`${BASE()}${path}`, {
      method,
      headers: {
        "X-Setup-Key": process.env.SETUP_KEY ?? "",
        ...(method === "POST" ? { "Content-Type": "application/json" } : {}),
      },
      body: method === "POST" ? JSON.stringify(body ?? {}) : undefined,
      cache: "no-store",
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      return { ok: false, error: data?.detail ?? `HTTP ${response.status}` };
    }
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "unknown error" };
  }
}
