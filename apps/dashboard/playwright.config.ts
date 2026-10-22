import { defineConfig } from "@playwright/test";

// The dashboard is exercised against fixture API routes only. The API origin
// points at a closed local port on purpose: any request that is not fulfilled by
// a test fixture must fail loudly instead of reaching the operator's real jobs,
// configuration, providers, or database.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: "../../data/renders/studio-e2e",
  use: {
    baseURL: "http://127.0.0.1:3217",
    browserName: "chromium",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3217",
    url: "http://127.0.0.1:3217",
    reuseExistingServer: false,
    timeout: 120000,
    env: { NODE_ENV: "development", STUDIO_API_ORIGIN: "http://127.0.0.1:9" },
  },
});
