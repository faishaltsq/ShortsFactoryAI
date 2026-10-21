import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:3018',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'uv run uvicorn apps.api.server:app --host 127.0.0.1 --port 8018',
      cwd: '../../',
      url: 'http://127.0.0.1:8018/api/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'npm run start',
      url: 'http://127.0.0.1:3018',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
