import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60 * 1000,
  use: {
    headless: false, // show in foreground
    viewport: { width: 1600, height: 900 },
    actionTimeout: 15 * 1000,
    navigationTimeout: 60 * 1000
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    }
  ]
});
