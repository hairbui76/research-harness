import { defineConfig } from '@playwright/test';

const port = Number(process.env.TASK_BROWSER_PORT ?? 8877);
export default defineConfig({
  testDir: './browser-tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 45_000,
  reporter: [['list'], ['html', { outputFolder: '.task-gate/playwright-report', open: 'never' }]],
  outputDir: '.task-gate/browser-results',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    browserName: 'chromium',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop-dark', use: { viewport: { width: 1440, height: 1000 }, colorScheme: 'dark' } },
    { name: 'narrow-light', use: { viewport: { width: 768, height: 1024 }, colorScheme: 'light' } },
  ],
  webServer: {
    command: 'uv run python scripts/browser_server.py',
    url: `http://127.0.0.1:${port}/api/app/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    env: { TASK_BROWSER_PORT: String(port) },
  },
});
