/**
 * Playwright script to capture the authenticated desktop home-page screenshot.
 *
 * Usage: node scripts/take-home-screenshot.cjs <email> <password>
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'http://localhost:5173';
const OUTPUT_DIR = path.join(__dirname, '..', 'public', 'marketing');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'home-page.png');

async function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  const [email, password] = process.argv.slice(2);
  if (!email || !password) {
    console.error('Usage: node scripts/take-home-screenshot.cjs <email> <password>');
    process.exit(1);
  }

  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();

  try {
    await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle' });
    await page.fill('input[type="email"]', email);
    await page.fill('input[type="password"]', password);
    await page.click('button[type="submit"]');

    await page.waitForURL(
      (url) => url.href.startsWith(`${BASE_URL}/home`) || url.href === `${BASE_URL}/`,
      { timeout: 20000 },
    );

    console.log('Capturing home page...');
    await page.goto(`${BASE_URL}/home`, { waitUntil: 'networkidle' });
    await delay(2000);
    await page.screenshot({ path: OUTPUT_FILE, fullPage: false });
    console.log(`  -> ${OUTPUT_FILE}`);
  } catch (err) {
    console.error('Screenshot failed:', err);
    await page.screenshot({ path: path.join(OUTPUT_DIR, 'error-screenshot.png'), fullPage: true });
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main();
