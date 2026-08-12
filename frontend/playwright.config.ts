import { defineConfig, devices } from "@playwright/test";

// No webServer block here on purpose: this suite exercises the real backend
// (Postgres-backed, dev-login-seeded) alongside the frontend, so both must be
// started manually first -- see README.md's "E2E smoke test" section for the
// exact commands. Wiring an auto-started webServer is CI work, out of scope here.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    // retries: 0 below means "on-first-retry" would never fire; keep the trace
    // from the one attempt that actually runs when it fails
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
