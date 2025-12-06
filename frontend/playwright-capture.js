import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const HOSTED_UI_URL = process.env.HOSTED_UI_URL || `https://popcorn-sales-manager-dev.auth.us-east-1.amazoncognito.com/oauth2/authorize?client_id=3218p1roiidl8jfudr3uqv4dvb&response_type=code&scope=email+openid+profile&redirect_uri=http://localhost:5173`;
const OUTDIR = process.env.OUTDIR || 'tests/e2e/results';

(async () => {
  const outDir = path.resolve(OUTDIR);
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await context.newPage();
  console.log(`Opening Managed Login UI: ${HOSTED_UI_URL}`);
  await page.goto(HOSTED_UI_URL, { waitUntil: 'networkidle' });

  await page.locator('text=Sign in').waitFor({ timeout: 30000 }).catch(() => null);

  // Capture full page screenshot
  const pagePng = path.join(outDir, 'cognito-page.png');
  await page.screenshot({ path: pagePng, fullPage: true });

  // Capture form screenshot
  const form = page.locator('form');
  const formExists = await form.count() > 0;
  const formPng = path.join(outDir, 'cognito-form.png');
  if (formExists) {
    await form.screenshot({ path: formPng });
  }

  // Detect primary button
  const signInButton = await page.getByRole('button', { name: /sign in/i }).first();
  const btnVisible = (await signInButton.count()) > 0 && await signInButton.isVisible();
  let primaryColor = null;
  if (btnVisible) {
    primaryColor = await signInButton.evaluate(el => window.getComputedStyle(el).backgroundColor);
  }

  // Detect page background color
  const pageBg = await page.evaluate(() => window.getComputedStyle(document.body).backgroundColor);

  // Detect link color
  const forgotLink = page.getByRole('link', { name: /forgot your password\?/i }).first();
  let linkColor = null;
  if ((await forgotLink.count()) > 0) {
    linkColor = await forgotLink.evaluate(el => window.getComputedStyle(el).color);
  }

  // Detect form logo
  let logoPresent = false;
  let logoSrc = null;
  const imgs = page.locator('img');
  const imgsCount = await imgs.count();
  for (let i = 0; i < imgsCount; i++) {
    const img = imgs.nth(i);
    if (await img.isVisible()) {
      const src = await img.getAttribute('src');
      if (src && (src.startsWith('data:') || /logo|cognito|popcorn/i.test(src))) {
        logoPresent = true;
        logoSrc = src;
        break;
      }
    }
  }

  // Detect favicon
  let faviconHref = null;
  try {
    faviconHref = await page.locator("link[rel='icon'], link[rel*='icon'], link[rel='shortcut icon']").first().evaluate(el => (el && el.href) ? el.href : null);
  } catch (e) {
    faviconHref = null;
  }

  const results = {
    url: HOSTED_UI_URL,
    timestamp: new Date().toISOString(),
    primaryButtonColor: primaryColor,
    pageBackgroundColor: pageBg,
    linkColor: linkColor,
    logoPresent: logoPresent,
    logoSrc: logoSrc,
    faviconHref: faviconHref,
    screenshots: {
      page: pagePng,
      form: formExists ? formPng : null
    }
  };

  const outJson = path.join(outDir, 'cognito-branding-results.json');
  fs.writeFileSync(outJson, JSON.stringify(results, null, 2), 'utf8');
  console.log('Saved results to', outJson);

  console.log('Preview open in foreground; press Ctrl+C when done.');

  // Keep browser open until user closes manually
  await new Promise(() => {});
})();
