import { test, expect } from '@playwright/test';

// Defaults: use env var HOSTED_UI_URL or construct it
const HOSTED_UI_URL = process.env.HOSTED_UI_URL || `https://popcorn-sales-manager-dev.auth.us-east-1.amazoncognito.com/oauth2/authorize?client_id=3218p1roiidl8jfudr3uqv4dvb&response_type=code&scope=email+openid+profile&redirect_uri=http://localhost:5173`;

// Expected colors in RGB (override with env var EXPECTED_PRIMARY_COLOR without #)
const expectedPrimaryHex = process.env.EXPECTED_PRIMARY_COLOR || '1976d2';
const primaryRgb = rgbFromHex(expectedPrimaryHex);
const pageBgRgb = 'rgb(245, 245, 245)'; // #f5f5f5

function rgbFromHex(hex: string) {
  // Accept hex like 1976d2 or #1976d2
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgb(${r}, ${g}, ${b})`;
}

test('Cognito Managed Login branding - visual checks', async ({ page }) => {
  await page.goto(HOSTED_UI_URL, { waitUntil: 'networkidle' });

  // Wait for login form heading
  await page.getByRole('heading', { name: /sign in/i }).waitFor({ timeout: 20000 });

  // Screenshot overall page
  await page.screenshot({ path: 'results/cognito-page.png', fullPage: true });

  // Primary button color
  const signInButton = await page.getByRole('button', { name: /sign in/i });
  await expect(signInButton).toBeVisible();
  const signInBg = await signInButton.evaluate((el) => window.getComputedStyle(el).backgroundColor);
  expect(signInBg).toBe(primaryRgb);

  // Link color: "Forgot your password?"
  const forgotLink = page.getByRole('link', { name: /forgot your password\?/i });
  await expect(forgotLink).toBeVisible();
  const linkColor = await forgotLink.evaluate((el) => window.getComputedStyle(el).color);
  expect(linkColor).toBe(primaryRgb);

  // Background color
  const bodyBg = await page.evaluate(() => window.getComputedStyle(document.body).backgroundColor);
  expect(bodyBg).toBe(pageBgRgb);

  // Logo presence: find any visible image that looks like the form logo
  const imgs = page.locator('img');
  const count = await imgs.count();
  let found = false;
  for (let i = 0; i < count; i++) {
    const img = imgs.nth(i);
    const visible = await img.isVisible();
    if (!visible) continue;
    const src = await img.getAttribute('src');
    // Consider data URI or filename that includes 'logo' or 'popcorn'
    if (src && (src.startsWith('data:') || /logo|popcorn|cognito/i.test(src))) {
      found = true;
      break;
    }
  }
  expect(found).toBeTruthy();

  // Favicon check
  const faviconEls = page.locator("link[rel='icon'], link[rel*='icon'], link[rel*='shortcut']");
  await expect(faviconEls.first()).toBeVisible({ timeout: 5000 }).catch(() => null);
  const faviconCount = await faviconEls.count();
  expect(faviconCount).toBeGreaterThan(0);

  // Save small screenshot of the form only
  const form = page.locator('form');
  await form.screenshot({ path: 'results/cognito-form.png' });

});
