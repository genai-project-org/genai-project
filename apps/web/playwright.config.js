import { defineConfig, devices } from '@playwright/test';

// Minimal e2e smoke layer, run against Vite's own dev server (no build step
// needed) on a dedicated port so it never collides with a locally running
// `yarn dev`. Only the Chromium project is configured because that's the
// only browser this environment has installed
// (`npx playwright install --with-deps chromium`); add firefox/webkit
// projects once those browsers are installed too.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'yarn dev --port 4173 --strictPort',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
