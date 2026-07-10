/**
 * Playwright script to capture a desktop reports-page screenshot with sample data.
 *
 * The screenshot excludes the top app header and shows a populated orders table.
 *
 * Usage: node scripts/take-reports-screenshot.cjs <email> <password>
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'http://localhost:5173';
const OUTPUT_DIR = path.join(__dirname, '..', 'public', 'marketing');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'reports-page.png');

const CUSTOMERS = [
  { name: 'Pat Taylor', phone: '555-0101', street: '123 Oak St', city: 'Anytown', state: 'OH', zip: '43001' },
  { name: 'Sam Rivera', phone: '555-0102', street: '456 Maple Ave', city: 'Springfield', state: 'OH', zip: '43002' },
  { name: 'Alex Chen', phone: '555-0103', street: '789 Pine Rd', city: 'Riverside', state: 'OH', zip: '43003' },
  { name: 'Jordan Morgan', phone: '555-0104', street: '321 Birch Ln', city: 'Hilltop', state: 'OH', zip: '43004' },
  { name: 'Casey Lee', phone: '555-0105', street: '654 Cedar Dr', city: 'Lakeside', state: 'OH', zip: '43005' },
  { name: 'Taylor Kim', phone: '555-0106', street: '987 Spruce Way', city: 'Meadowbrook', state: 'OH', zip: '43006' },
];

async function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function login(page, email, password) {
  console.log('Logging in...');
  await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle' });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await page.waitForURL((url) => url.href.startsWith(`${BASE_URL}/home`) || url.href === `${BASE_URL}/`, {
    timeout: 20000,
  });
  await delay(1500);
}

async function ensureProfile(page) {
  await page.goto(`${BASE_URL}/scouts`, { waitUntil: 'networkidle' });
  await delay(1500);

  // Count visible profile cards by looking for seller names / manage buttons
  const manageButtons = page.locator('button:has-text("Manage Scout")');
  const count = await manageButtons.count();
  if (count > 0) {
    console.log(`Found ${count} existing profile(s).`);
    return;
  }

  console.log('Creating scout profile...');
  await page.getByRole('button', { name: 'Create Scout' }).click();
  await page.getByRole('dialog').waitFor({ state: 'visible' });
  await page.getByLabel('Scout Name').fill('Jamie');
  await page.getByRole('button', { name: 'Create Scout' }).click();
  await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await delay(1000);
}

async function ensureCampaign(page) {
  await page.goto(`${BASE_URL}/scouts`, { waitUntil: 'networkidle' });
  await delay(1500);

  const viewCampaigns = page.locator('button:has-text("View All Campaigns")').first();
  if (await viewCampaigns.isVisible().catch(() => false)) {
    await viewCampaigns.click();
    await page.waitForURL((url) => url.href.includes('/campaigns'), { timeout: 10000 });
    await delay(1500);
  }

  const newCampaign = page.locator('button:has-text("New Campaign")').first();
  if (!(await newCampaign.isVisible().catch(() => false))) {
    console.log('Using existing campaign.');
    return;
  }

  console.log('Creating campaign...');
  await newCampaign.click();
  await page.waitForURL((url) => url.href.includes('/create-campaign'), { timeout: 10000 });
  await delay(1500);

  // Select first profile
  const profileSelect = page.getByLabel('Select Profile');
  if (await profileSelect.isVisible().catch(() => false)) {
    await profileSelect.click();
    await page.getByRole('option').filter({ hasNot: page.getByText('Select Profile') }).first().click();
    await delay(300);
  }

  await page.getByLabel('Campaign Name').fill('Fall 2026 Popcorn Sale');
  await page.getByLabel('Year').fill('2026');

  // Select first catalog
  const catalogSelect = page.getByLabel('Select Catalog');
  if (await catalogSelect.isVisible().catch(() => false)) {
    await catalogSelect.click();
    await page.getByRole('option').filter({ hasNot: page.getByText('Public Catalogs') }).first().click();
    await delay(300);
  }

  const submitButton = page.getByRole('button', { name: 'Create Campaign', exact: true });
  await submitButton.click();
  await page.waitForURL((url) => url.href.includes('/campaigns/') && !url.href.endsWith('/campaigns') && !url.href.includes('/create-campaign'), { timeout: 20000 });
  await delay(1500);
}

async function ensureOrders(page) {
  await page.getByRole('tab', { name: 'Orders' }).click().catch(() => {});
  await delay(1000);

  const existingOrders = await page.locator('table tbody tr').count();
  if (existingOrders >= 6) {
    console.log(`Found ${existingOrders} orders, skipping creation.`);
    return;
  }

  console.log('Creating fake orders...');
  for (let i = 0; i < CUSTOMERS.length; i++) {
    const newOrderButton = page.locator('button:has-text("New Order")').first();
    await newOrderButton.click();
    await page.waitForURL((url) => url.href.includes('/orders/new'), { timeout: 10000 });
    await delay(1000);

    const customer = CUSTOMERS[i];
    await page.getByLabel('Customer Name').fill(customer.name);
    await page.getByLabel('Phone Number').fill(customer.phone);
    await page.getByLabel('Street Address').fill(customer.street);
    await page.getByLabel('City').fill(customer.city);
    const stateInput = page.getByLabel('State');
    if (await stateInput.isVisible().catch(() => false)) {
      await stateInput.fill(customer.state);
      await page.keyboard.press('Escape');
    }
    await page.getByLabel('Zip Code').fill(customer.zip);

    // Select first product in the products table
    const productRow = page.locator('table tbody tr').first();
    const productSelect = productRow.locator('[role="combobox"]').first();
    if (await productSelect.isVisible().catch(() => false)) {
      await productSelect.click();
      await delay(200);
      // Skip placeholder options and pick first real product
      const options = page.getByRole('option');
      const count = await options.count();
      for (let o = 0; o < count; o++) {
        const text = await options.nth(o).textContent();
        if (text && !text.toLowerCase().includes('select') && !text.toLowerCase().includes('product')) {
          await options.nth(o).click();
          break;
        }
      }
      await delay(200);
    }

    // Fill quantity for the first product row
    const qtyInput = productRow.locator('input[type="number"]').first();
    if (await qtyInput.isVisible().catch(() => false)) {
      await qtyInput.fill(String(Math.floor(Math.random() * 3) + 1));
    }

    await page.getByRole('button', { name: 'Create Order' }).click();
    await page.waitForURL((url) => !url.href.includes('/orders/new'), { timeout: 20000 });
    await delay(1000);
  }
}

async function takeScreenshot(page) {
  console.log('Navigating to reports...');
  await page.getByRole('tab', { name: 'Reports' }).click().catch(() => {});
  await delay(2000);

  // Hide app header, page breadcrumbs/tabs, and dev build bar for the screenshot
  await page.addStyleTag({
    content: `
      header.MuiAppBar-root,
      .MuiAppBar-root,
      [role="banner"],
      .MuiBottomNavigation-root,
      nav,
      [role="tablist"],
      .MuiTabs-root {
        display: none !important;
      }
      body {
        padding-top: 0 !important;
      }
    `,
  });

  // Hide the page header (back arrow + campaign title) and dev build bar
  await page.evaluate(() => {
    // Hide dev build bar
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.textContent && node.textContent.includes('DEV | v')) {
        let el = node.parentElement;
        while (el && el !== document.body) {
          if (el.tagName === 'DIV' || el.tagName === 'FOOTER') {
            el.style.display = 'none';
            break;
          }
          el = el.parentElement;
        }
      }
    }

    // Hide page title header that contains the campaign name and back arrow
    const headers = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
    for (const header of headers) {
      if (header.textContent && header.textContent.includes('Popcorn Sale')) {
        let el = header;
        while (el && el !== document.body && el.parentElement?.children.length <= 3) {
          el = el.parentElement;
        }
        el.style.display = 'none';
      }
    }
  });
  await delay(500);

  await page.evaluate(() => window.scrollTo(0, 0));
  await delay(500);

  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  const scrollY = await page.evaluate(() => window.scrollY);
  await page.screenshot({
    path: OUTPUT_FILE,
    clip: {
      x: 240,
      y: scrollY,
      width: 1040,
      height: 1100,
    },
  });

  console.log(`Screenshot saved to ${OUTPUT_FILE}`);
}

async function main() {
  const [email, password] = process.argv.slice(2);
  if (!email || !password) {
    console.error('Usage: node scripts/take-reports-screenshot.cjs <email> <password>');
    process.exit(1);
  }

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1200 } });

  try {
    await login(page, email, password);
    await ensureProfile(page);
    await ensureCampaign(page);
    await ensureOrders(page);
    await takeScreenshot(page);
  } catch (err) {
    console.error('Screenshot failed:', err);
    await page.screenshot({ path: path.join(OUTPUT_DIR, 'error-screenshot.png'), fullPage: true });
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main();
