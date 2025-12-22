/**
 * E2E Tests for CreateCampaignPage - Shared Campaign Flow
 *
 * Tests the unauthenticated redirect, shared campaign code entry, and campaign discovery flows.
 *
 * NOTE: These tests require:
 * 1. A running backend (CDK deployed to dev)
 * 2. Valid test data (shared campaigns, catalogs)
 * 3. Test user accounts for authentication flows
 *
 * For now, tests are marked as skipped until the backend is fully deployed
 * and test data infrastructure is in place.
 */

import { test, expect } from "@playwright/test";

test.describe("CreateCampaignPage - Unauthenticated Redirect", () => {
  test.skip("redirects unauthenticated user to login when accessing /c/:sharedCampaignCode", async ({
    page,
  }) => {
    // Navigate to a shared campaign code URL without being logged in
    await page.goto("/c/TEST1234");

    // Should redirect to login page
    await expect(page).toHaveURL(/.*login/);

    // Should preserve the return URL
    const url = page.url();
    expect(url).toContain("returnTo");
  });

  test.skip("preserves shared campaign code in session after login redirect", async ({ page }) => {
    // Navigate to shared campaign URL
    await page.goto("/c/TEST1234");

    // Complete login flow (would need test credentials)
    // await page.fill('[name="email"]', 'test@example.com');
    // await page.click('button[type="submit"]');

    // After login, should redirect back to /c/TEST1234
    // await expect(page).toHaveURL('/c/TEST1234');
  });
});

test.describe("CreateCampaignPage - Manual Mode", () => {
  test.skip("displays create campaign form at /create-campaign", async ({ page }) => {
    // Would need to be logged in first
    await page.goto("/create-campaign");

    // Should show the form title
    await expect(page.getByText("Create New Campaign")).toBeVisible();

    // Should show profile selection
    await expect(page.getByLabel(/Select Profile/i)).toBeVisible();

    // Should show catalog selection
    await expect(page.getByLabel(/Select Catalog/i)).toBeVisible();

    // Should show Unit Information accordion
    await expect(page.getByText("Unit Information")).toBeVisible();
  });

  test.skip("unit fields are optional but validated together", async ({ page }) => {
    await page.goto("/create-campaign");

    // Expand unit accordion
    await page.getByText("Unit Information").click();

    // Fill unit type only
    await page.getByLabel(/Unit Type/i).click();
    await page.getByRole("option", { name: /Pack/i }).click();

    // Should show validation error that other fields required
    // when unit type is selected
    await expect(page.getByText(/Unit number is required/i)).toBeVisible();
  });
});

test.describe("CreateCampaignPage - Prefill Mode", () => {
  test.skip("displays locked fields when valid shared campaign code provided", async ({ page }) => {
    // Would need a valid shared campaign code in the database
    await page.goto("/c/VALID123");

    // Should show shared campaign mode banner
    await expect(page.getByText(/Campaign sharedCampaign/i)).toBeVisible();

    // Fields should be disabled
    const campaignNameInput = page.getByLabel(/Campaign Name/i);
    await expect(campaignNameInput).toBeDisabled();
  });

  test.skip("shows creator message when provided in sharedCampaign", async ({ page }) => {
    await page.goto("/c/VALID123");

    // Should display the creator's message
    await expect(page.getByText(/Message from/i)).toBeVisible();
  });

  test.skip("share checkbox is checked by default", async ({ page }) => {
    await page.goto("/c/VALID123");

    // Share checkbox should be checked
    const shareCheckbox = page.getByRole("checkbox", { name: /share/i });
    await expect(shareCheckbox).toBeChecked();
  });

  test.skip("shows warning about sharing access", async ({ page }) => {
    await page.goto("/c/VALID123");

    // Should show the warning text
    await expect(
      page.getByText(/read access to ALL current and future campaigns/i)
    ).toBeVisible();
  });
});

test.describe("CreateCampaignPage - Campaign Discovery", () => {
  test.skip("detects matching shared campaign when unit fields match", async ({ page }) => {
    await page.goto("/create-campaign");

    // Fill in all required fields that match a shared campaign
    await page.getByLabel(/Select Profile/i).click();
    await page.getByRole("option").first().click();

    await page.getByLabel(/Campaign Name/i).fill("Fall 2024");
    await page.getByLabel(/Year/i).fill("2024");

    // Expand and fill unit info
    await page.getByText("Unit Information").click();
    await page.getByLabel(/Unit Type/i).click();
    await page.getByRole("option", { name: /Pack/i }).click();
    await page.getByLabel(/Unit Number/i).fill("123");
    await page.getByLabel(/City/i).fill("Denver");
    await page.getByLabel(/State/i).click();
    await page.getByRole("option", { name: /Colorado/i }).click();

    // Should detect matching shared campaign after debounce
    await expect(page.getByText(/matching shared campaign found/i)).toBeVisible({
      timeout: 2000,
    });
  });

  test.skip("allows user to use discovered sharedCampaign", async ({ page }) => {
    // After discovery alert appears
    await page.goto("/create-campaign");
    // ... fill fields to trigger discovery ...

    // Click to use the shared campaign
    await page.getByRole("button", { name: /use this sharedCampaign/i }).click();

    // Should redirect to shared campaign URL
    await expect(page).toHaveURL(/\/c\//);
  });
});

test.describe("CreateCampaignPage - Form Submission", () => {
  test.skip("successfully creates campaign in manual mode", async ({ page }) => {
    await page.goto("/create-campaign");

    // Fill required fields
    await page.getByLabel(/Select Profile/i).click();
    await page.getByRole("option").first().click();

    await page.getByLabel(/Campaign Name/i).fill("Test Campaign");
    await page.getByLabel(/Year/i).fill("2024");

    await page.getByLabel(/Select Catalog/i).click();
    await page.getByRole("option").first().click();

    // Submit
    await page.getByRole("button", { name: /Create Campaign/i }).click();

    // Should show success and redirect
    await expect(page.getByText(/Campaign created/i)).toBeVisible();
  });

  test.skip("successfully creates campaign in shared campaign mode", async ({ page }) => {
    await page.goto("/c/VALID123");

    // Just select a profile (other fields pre-filled)
    await page.getByLabel(/Select Profile/i).click();
    await page.getByRole("option").first().click();

    // Submit
    await page.getByRole("button", { name: /Create Campaign/i }).click();

    // Should show success
    await expect(page.getByText(/Campaign created/i)).toBeVisible();
  });
});
