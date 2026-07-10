/**
 * Playwright script to capture mobile-viewport screenshots of authenticated pages.
 *
 * Usage: node scripts/take-mobile-screenshots.cjs <email> <password>
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'http://localhost:5173';
const OUTPUT_DIR = path.join(__dirname, '..', 'public', 'marketing');

const screenshots = [
  { name: 'home-page-mobile.png', route: '/home', label: 'Home dashboard' },
  { name: 'scouts-page-mobile.png', route: '/scouts', label: 'My Scouts' },
  { name: 'payment-methods-page-mobile.png', route: '/payment-methods', label: 'Payment Methods' },
  { name: 'reports-page-mobile.png', route: '/campaign-reports', label: 'Campaign Reports' },
];

async function main() {
  const [email, password] = process.argv.slice(2);
  if (!email || !password) {
    console.error('Usage: node scripts/take-mobile-screenshots.cjs <email> <password>');
    process.exit(1);
  }

  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    userAgent:
      'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
  });
  const page = await context.newPage();

  try {
    // Navigate to login page and sign in with email/password
    await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle' });
    await page.fill('input[type="email"]', email);
    await page.fill('input[type="password"]', password);
    await page.click('button[type="submit"]');

    // Wait for navigation to authenticated app
    await page.waitForURL((url) => url.href.startsWith(`${BASE_URL}/home`) || url.href === `${BASE_URL}/`, {
      timeout: 20000,
    });

    // If redirected to /home or /, navigate to target pages
    for (const shot of screenshots) {
      console.log(`Capturing ${shot.label}...`);
      await page.goto(`${BASE_URL}${shot.route}`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(2000);
      const outputPath = path.join(OUTPUT_DIR, shot.name);
      await page.screenshot({ path: outputPath, fullPage: false });
      console.log(`  -> ${outputPath}`);
    }

    // Collaborate screenshot: open the first scout's manage page.
    console.log('Capturing collaborate screenshot from manage page...');
    await page.goto(`${BASE_URL}/scouts`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1500);
    await page.click('button:has-text("Manage Scout")');
    await page.waitForURL((url) => url.href.includes('/manage'), { timeout: 10000 });
    await page.waitForTimeout(1500);
    const collaboratePath = path.join(OUTPUT_DIR, 'collaborate-page-mobile.png');
    await page.screenshot({ path: collaboratePath, fullPage: false });
    console.log(`  -> ${collaboratePath}`);
  } catch (err) {
    console.error('Screenshot failed:', err);
    await page.screenshot({ path: path.join(OUTPUT_DIR, 'error-screenshot.png'), fullPage: true });
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main();
