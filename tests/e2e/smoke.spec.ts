import { expect, test } from "@playwright/test";

/** Can a broken build reach production quietly? These run against `next
 * start` with no Python API and no database — the most degraded state the
 * app can serve from — so they assert resilience, not features. */

test("the sign-in page renders even with no backend", async ({ page }) => {
  const response = await page.goto("/login");
  expect(response?.status()).toBe(200);
  await expect(page).toHaveTitle(/Sign in · Navtek/);
  await expect(page.getByText("eOrder & installs")).toBeVisible();
  // Degraded is allowed; a blank page or an error boundary is not.
  await expect(page.locator(".auth-card")).toBeVisible();
});

test("an unauthenticated visit is bounced to sign-in", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("the gated pages all bounce rather than break", async ({ page }) => {
  for (const path of ["/deliveries", "/sla", "/activity", "/users", "/orders/123"]) {
    await page.goto(path);
    await expect(page, `${path} should bounce to /login`).toHaveURL(/\/login$/);
  }
});
