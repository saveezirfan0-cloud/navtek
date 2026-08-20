import { defineConfig } from "@playwright/test";

/** The smoke run: boot the BUILT app (next start — run `npm run build` first)
 * and prove the shell serves. No Python API and no database behind it, so the
 * assertions stick to what must hold even fully degraded: pages render, the
 * auth gate redirects, nothing 500s. */
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:3100",
    // Sandboxes with a preinstalled Chromium point this at its binary
    // instead of downloading a build to match the package version.
    ...(process.env.CHROMIUM_PATH
      ? { launchOptions: { executablePath: process.env.CHROMIUM_PATH } }
      : {}),
  },
  webServer: {
    command: "npx next start --port 3100",
    url: "http://127.0.0.1:3100/login",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
