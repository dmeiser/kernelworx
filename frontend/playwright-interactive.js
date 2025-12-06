import { chromium } from 'playwright';

const HOSTED_UI_URL = process.env.HOSTED_UI_URL || `https://popcorn-sales-manager-dev.auth.us-east-1.amazoncognito.com/oauth2/authorize?client_id=3218p1roiidl8jfudr3uqv4dvb&response_type=code&scope=email+openid+profile&redirect_uri=http://localhost:5173`;

(async () => {
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await context.newPage();
  console.log(`Opening Managed Login UI: ${HOSTED_UI_URL}`);
  await page.goto(HOSTED_UI_URL, { waitUntil: 'networkidle' });

  // Wait for form heading
  await page.locator('text=Sign in').waitFor({ timeout: 30000 }).catch(() => null);

  // Show the page and keep the browser open for interactive view
  console.log('Page loaded: you should be able to see it in the foreground. Press Ctrl+C to exit when done.');

  // Optionally keep running until SIGINT
  await new Promise(() => {});
})();
