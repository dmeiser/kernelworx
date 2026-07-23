#!/usr/bin/env python3
# ruff: noqa: E402
"""Capture marketing screenshots for KernelWorx using the Alex Kernel user.

Usage:
    uv run python scripts/capture-screenshots.py

Prerequisites:
    - scripts/create-screenshot-user.sh has been run.
    - .env contains TEST_ALEX_EMAIL, TEST_ALEX_PASSWORD, and E2E_BASE_URL.
    - Playwright Chromium is installed (uv run playwright install chromium).

Screenshots are written to frontend/public/marketing/ and overwrite any
existing files with the same names.

Cleanup:
    The script intentionally preserves all created data so screenshots can be
    re-captured later. To remove Alex Kernel and their data, see the cleanup
    notes at the bottom of this file.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
from pathlib import Path

# Make the repo root importable so we can reuse the e2e page objects.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from playwright.sync_api import Browser, Page, expect, sync_playwright

from tests.e2e.pages.base_page import BasePage
from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.login_page import LoginPage
from tests.e2e.pages.order_page import OrderPage
from tests.e2e.pages.payment_page import PaymentPage
from tests.e2e.pages.reports_page import ReportsPage
from tests.e2e.pages.share_page import SharePage
from tests.e2e.utils.auth import login_as_readonly

load_dotenv(ROOT / ".env")

DESKTOP_VIEWPORT = {"width": 1440, "height": 1200}
MOBILE_VIEWPORT = {"width": 390, "height": 844}

# Per-page clip regions (CSS pixels) for authenticated desktop screenshots.
# These mirror the original prod marketing assets: header/sidebar removed and
# the crop is tight around the meaningful content.
HOME_PAGE_CLIP = {"x": 240, "y": 64, "width": 1200, "height": 836}
SCOUTS_PAGE_CLIP = {"x": 264, "y": 230, "width": 1152, "height": 460}
PAYMENT_METHODS_CLIP = {"x": 264, "y": 200, "width": 1152, "height": 360}
REPORTS_PAGE_CLIP = {"x": 240, "y": 320, "width": 1200, "height": 795}
COLLABORATE_PAGE_CLIP = {"x": 264, "y": 360, "width": 1152, "height": 360}

UNAUTH_SCREENSHOTS = [
    ("landing-page.png", "/"),
    ("login-page.png", "/login"),
]

AUTH_SCREENSHOTS = {
    "desktop": [
        ("home-page.png", "/home", HOME_PAGE_CLIP),
        ("scouts-page.png", "/scouts", SCOUTS_PAGE_CLIP),
        ("payment-methods-page.png", "/payment-methods", PAYMENT_METHODS_CLIP),
        ("reports-page.png", None, REPORTS_PAGE_CLIP),  # path computed at runtime
        ("collaborate-page.png", None, COLLABORATE_PAGE_CLIP),  # path computed at runtime
    ],
    "mobile": [
        ("home-page-mobile.png", "/home"),
        ("scouts-page-mobile.png", "/scouts"),
        ("payment-methods-page-mobile.png", "/payment-methods"),
        ("collaborate-page-mobile.png", None),  # path computed at runtime
    ],
}


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Required environment variable '{name}' is not set in .env")
    return value


def login_as_alex(page: Page) -> None:
    """Log in as Alex Kernel using the shared LoginPage POM."""
    email = _require_env("TEST_ALEX_EMAIL")
    password = _require_env("TEST_ALEX_PASSWORD")
    login_page = LoginPage(page)
    login_page.goto()
    login_page.login(email, password)
    login_page.wait_for_redirect()


def wait_for_welcome(page: Page) -> None:
    """Wait until the authenticated home page shows Alex is signed in."""
    expect(page.get_by_role("heading", name=re.compile(r"Welcome back")).first).to_be_visible(timeout=15_000)


def _wait_for_dashboard_ready(page: Page) -> None:
    """Wait until the scouts dashboard has loaded profiles or its empty state."""
    BasePage(page).wait_for_loading()
    profile_heading = page.locator("div.MuiCard-root h3").first
    empty_state = page.get_by_text("No Scouts Yet", exact=False)
    expect(profile_heading.or_(empty_state)).to_be_visible(timeout=15_000)


def _delete_profile(page: Page, name: str) -> None:
    """Delete a seller profile by navigating to its manage page and confirming deletion."""
    dashboard = DashboardPage(page)
    dashboard.goto()
    _wait_for_dashboard_ready(page)
    card = page.locator("div.MuiCard-root").filter(has_text=name).first
    expect(card).to_be_visible(timeout=10_000)
    card.get_by_role("button", name="Manage Scout", exact=True).click()
    page.wait_for_url("**/manage", timeout=15_000)
    BasePage(page).wait_for_loading()

    # Scroll to and click the Delete Scout button in the Danger Zone.
    delete_button = page.get_by_role("button", name="Delete Scout", exact=True)
    expect(delete_button).to_be_visible(timeout=10_000)
    delete_button.click()

    confirm = page.get_by_role("button", name="Delete Permanently", exact=True)
    expect(confirm).to_be_visible(timeout=10_000)
    confirm.click()

    # Wait for redirect back to the dashboard and the card to disappear.
    page.wait_for_url("**/scouts", timeout=15_000)
    BasePage(page).wait_for_loading()
    expect(card).to_be_hidden(timeout=15_000)
    print(f"  Deleted profile: {name}")


def ensure_profiles(page: Page) -> list[str]:
    """Ensure only the three target profiles exist, deleting any extras."""
    dashboard = DashboardPage(page)
    dashboard.goto()
    _wait_for_dashboard_ready(page)

    targets = ["Alex Kernel", "Jordan Kernel", "Taylor Kernel", "Casey Kernel", "Riley Kernel", "Morgan Kernel"]
    existing = set(dashboard.get_profile_names())

    # Remove profiles left over from previous screenshot runs.
    for name in existing - set(targets):
        _delete_profile(page, name)

    for name in targets:
        if name in existing:
            print(f"  Profile already exists: {name}")
            continue
        print(f"  Creating profile: {name}")
        dashboard._create_scout_button().click()
        dialog = page.get_by_role("dialog")
        page.get_by_label("Scout Name").fill(name)
        page.get_by_role("button", name="Create Scout").click()
        expect(dialog).to_be_hidden(timeout=15_000)
        dashboard.wait_for_loading()
        _wait_for_dashboard_ready(page)

    # Return the full list in a deterministic order.
    dashboard.goto()
    _wait_for_dashboard_ready(page)
    return dashboard.get_profile_names()


def _profile_id_from_url(url: str) -> str:
    match = re.search(r"/scouts/([^/]+)/campaigns", url)
    if not match:
        raise RuntimeError(f"Could not extract profileId from URL: {url}")
    return urllib.parse.unquote(match.group(1))


def ensure_campaign(page: Page, profile_name: str, campaign_name: str) -> tuple[str, str]:
    """Ensure Alex's first profile has a campaign; return (profile_id, campaign_id)."""
    dashboard = DashboardPage(page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()

    dashboard.click_profile(profile_name)
    profile_id = _profile_id_from_url(page.url)

    campaign_page = CampaignPage(page)
    campaign_page.wait_for_loading()
    campaigns = campaign_page.get_campaign_names()
    if campaign_name in campaigns:
        print(f"  Campaign already exists: {campaign_name}")
        campaign_page.click_campaign(campaign_name)
    else:
        print(f"  Creating campaign: {campaign_name}")
        campaign_page.create_campaign_first_catalog(campaign_name, profile_id)
        campaign_page.click_campaign(campaign_name)

    match = re.search(r"/scouts/[^/]+/campaigns/([^/?#]+)", page.url)
    if not match:
        raise RuntimeError(f"Could not extract campaignId from URL: {page.url}")
    campaign_id = urllib.parse.unquote(match.group(1))
    return profile_id, campaign_id


def _payment_method_headings(page: Page) -> list[str]:
    """Return the visible payment-method name headings (MUI Typography h6 spans)."""
    return page.locator("div.MuiCard-root .MuiTypography-h6").all_inner_texts()


def ensure_payment_methods(page: Page) -> None:
    """Add Venmo and PayPal custom payment methods if missing.

    The shared PaymentPage.has_payment_method() can match the empty-state
    card's body text for common names like "Venmo", so we compare exact
    card headings instead.
    """
    payment_page = PaymentPage(page)
    payment_page.goto()
    names = _payment_method_headings(page)
    for method in ("Venmo", "PayPal"):
        if method in names:
            print(f"  Payment method already exists: {method}")
            continue
        print(f"  Adding payment method: {method}")
        payment_page.add_payment_method(method)
        # Wait for the new method heading to appear in the list.
        expect(
            page.locator("div.MuiCard-root .MuiTypography-h6", has_text=method)
        ).to_be_visible(timeout=10_000)


def _create_order_with_options(
    page: Page,
    profile_id: str,
    campaign_id: str,
    customer_name: str,
    product_index: int,
    quantity: int,
    payment_method: str,
    address: dict[str, str] | None = None,
) -> None:
    """Create a single order with a specific product and payment method."""
    order_page = OrderPage(page)
    order_page.goto(profile_id, campaign_id)
    order_page.wait_for_loading()

    order_page._new_order_button().click()
    order_page.wait_for_loading()

    # Customer info
    page.get_by_label("Customer Name").fill(customer_name)
    page.get_by_label("Phone Number").fill("5551234567")
    if address:
        page.get_by_label("Street Address", exact=True).fill(address.get("street", ""))
        page.get_by_label("City", exact=True).fill(address.get("city", ""))
        page.get_by_label("State", exact=True).fill(address.get("state", ""))
        page.get_by_label("Zip Code", exact=True).fill(address.get("zip", ""))

    # Product selection: collect options and pick the requested one.
    product_row = page.get_by_role("row").nth(1)
    product_row.get_by_role("combobox").click()
    options = page.get_by_role("option").all()
    if product_index >= len(options):
        product_index = 0
    options[product_index].click()
    product_row.locator('input[type="number"]').fill(str(quantity))

    # Payment method (locate inside the "Payment & Notes" card)
    payment_card = page.locator("div.MuiPaper-root").filter(has_text="Payment & Notes")
    payment_select = payment_card.get_by_role("combobox")
    expect(payment_select).to_be_visible(timeout=10_000)
    payment_select.click()

    # Poll until the async payment-methods query has finished loading.
    for _ in range(30):
        options = page.get_by_role("option").all()
        option_names = [opt.inner_text() for opt in options]
        if payment_method in option_names:
            break
        if "Loading..." in option_names:
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
            payment_select.click()
        else:
            page.wait_for_timeout(250)
    else:
        raise RuntimeError(f"Payment method '{payment_method}' never appeared in the dropdown")

    page.get_by_role("option", name=payment_method).click()

    # Submit and return to orders list.
    order_page._create_order_button().click()
    page.wait_for_url("**/orders", timeout=15_000)
    order_page.wait_for_loading()
    print(f"  Created order for {customer_name} ({payment_method})")


def ensure_orders(page: Page, profile_id: str, campaign_id: str) -> None:
    """Create a varied set of orders with plausible names and addresses."""
    orders = [
        ("Sarah Johnson", 0, 2, "Cash", {"street": "123 Maple St", "city": "Springfield", "state": "IL", "zip": "62701"}),
        ("Mike Chen", 1, 1, "Venmo", {"street": "456 Oak Ave", "city": "Bloomington", "state": "IL", "zip": "61701"}),
        ("Lisa Rodriguez", 0, 3, "PayPal", {"street": "789 Pine Rd", "city": "Decatur", "state": "IL", "zip": "62521"}),
        ("David Miller", 1, 2, "Check", {"street": "321 Birch Ln", "city": "Champaign", "state": "IL", "zip": "61820"}),
        ("Emily Davis", 0, 1, "Cash", {"street": "654 Cedar Dr", "city": "Peoria", "state": "IL", "zip": "61602"}),
        ("James Wilson", 1, 4, "Venmo", {"street": "987 Walnut St", "city": "Normal", "state": "IL", "zip": "61761"}),
        ("Emma Brown", 0, 2, "PayPal", {"street": "147 Elm St", "city": "Quincy", "state": "IL", "zip": "62301"}),
        ("Michael Garcia", 1, 1, "Check", {"street": "258 Spruce Ave", "city": "Rockford", "state": "IL", "zip": "61101"}),
    ]
    order_page = OrderPage(page)
    order_page.goto(profile_id, campaign_id)
    existing_customers = {cell.inner_text() for cell in page.get_by_role("cell").all()}

    for customer, product_index, quantity, payment, address in orders:
        if customer in existing_customers:
            print(f"  Order already exists for {customer}")
            continue
        _create_order_with_options(
            page, profile_id, campaign_id, customer, product_index, quantity, payment, address
        )


def ensure_share_invite(page: Page, profile_id: str, browser: Browser, base_url: str) -> None:
    """Generate a READ invite and accept it as the readonly test user.

    The share management page shows a real shared user in the table only after
    the invite has been redeemed, so we log in as the readonly user in a fresh
    browser context and accept the generated code.
    """
    share_page = SharePage(page)
    share_page.goto(profile_id)
    invite_code = share_page.get_invite_link()
    if not invite_code:
        print("  Generating share invite")
        share_page.create_invite("READ")
        invite_code = share_page.get_invite_link()
    else:
        print("  Share invite already visible")

    if not invite_code:
        raise RuntimeError("Could not obtain an invite code")

    # Accept the invite in a separate context so Alex's session is untouched.
    print("  Accepting invite as readonly user")
    readonly_context = browser.new_context(
        viewport=DESKTOP_VIEWPORT,
        device_scale_factor=1,
        base_url=base_url,
        ignore_https_errors=True,
    )
    readonly_page = readonly_context.new_page()
    try:
        login_as_readonly(readonly_page)
        SharePage(readonly_page).accept_invite(invite_code)
        print("  Invite accepted")
    finally:
        readonly_context.close()

    # Generate a fresh invite so the manage page shows an active invite code
    # alongside the accepted share in the "Who Has Access" table.
    print("  Generating second invite for screenshot")
    share_page.goto(profile_id)
    share_page.create_invite("READ")


def setup_data(page: Page, browser: Browser, base_url: str) -> tuple[str, str]:
    """Create all the seed data needed for screenshots."""
    print("Setting up screenshot data...")
    ensure_profiles(page)
    profile_name = "Alex Kernel"

    profile_id, campaign_id = ensure_campaign(page, profile_name, "2025 Popcorn Sale")
    ensure_payment_methods(page)
    ensure_orders(page, profile_id, campaign_id)
    ensure_share_invite(page, profile_id, browser, base_url)
    print("Setup complete.")
    return profile_id, campaign_id


def scroll_top(page: Page) -> None:
    page.evaluate("window.scrollTo(0, 0)")


def wait_for_page_ready(page: Page, path: str | None) -> None:
    """Generic wait for page load and spinner disappearance."""
    BasePage(page).wait_for_loading()
    if path == "/":
        expect(page.get_by_role("heading", name="Use it on your own", exact=False)).to_be_visible(timeout=15_000)
    elif path == "/login":
        expect(page.locator('input[type="email"]').first).to_be_visible(timeout=15_000)
    elif path == "/home":
        wait_for_welcome(page)
    elif path == "/scouts":
        expect(page.get_by_text("Create Scout").first).to_be_visible(timeout=15_000)
    elif path == "/payment-methods":
        expect(page.get_by_text("Add Payment Method").first).to_be_visible(timeout=15_000)


def capture_unauth(page: Page, output_dir: Path) -> None:
    """Capture public marketing screenshots without logging in."""
    print("Capturing unauthenticated screenshots...")
    for filename, path in UNAUTH_SCREENSHOTS:
        BasePage(page).navigate(path)
        wait_for_page_ready(page, path)
        scroll_top(page)
        page.wait_for_timeout(500)
        output_path = output_dir / filename
        # The marketing landing page is a long scroll; capture the full page.
        page.screenshot(path=str(output_path), full_page=(path == "/"))
        print(f"  {output_path} ({output_path.stat().st_size} bytes)")


def capture_desktop(
    page: Page,
    output_dir: Path,
    profile_id: str,
    campaign_id: str,
) -> None:
    """Capture all authenticated desktop screenshots clipped to the content area."""
    print("Capturing authenticated desktop screenshots...")
    for filename, path, clip in AUTH_SCREENSHOTS["desktop"]:
        if path is None:
            if filename == "reports-page.png":
                reports = ReportsPage(page)
                reports.goto(profile_id, campaign_id)
            elif filename == "collaborate-page.png":
                SharePage(page).goto(profile_id)
            else:
                raise RuntimeError(f"Unhandled desktop screenshot: {filename}")
        else:
            BasePage(page).navigate(path)
            wait_for_page_ready(page, path)

        scroll_top(page)
        page.wait_for_timeout(500)
        output_path = output_dir / filename
        page.screenshot(path=str(output_path), clip=clip)
        print(f"  {output_path} ({output_path.stat().st_size} bytes)")


def capture_mobile(
    browser: Browser,
    base_url: str,
    output_dir: Path,
    profile_id: str,
    campaign_id: str,
) -> None:
    """Capture mobile screenshots in a fresh authenticated context."""
    print("Capturing mobile screenshots...")
    context = browser.new_context(
        viewport=MOBILE_VIEWPORT,
        device_scale_factor=2,
        base_url=base_url,
        ignore_https_errors=True,
    )
    page = context.new_page()
    try:
        login_as_alex(page)
        wait_for_welcome(page)

        for filename, path in AUTH_SCREENSHOTS["mobile"]:
            if filename == "collaborate-page-mobile.png":
                SharePage(page).goto(profile_id)
            else:
                BasePage(page).navigate(path)
                wait_for_page_ready(page, path)

            scroll_top(page)
            page.wait_for_timeout(500)
            output_path = output_dir / filename
            page.screenshot(path=str(output_path))
            print(f"  {output_path} ({output_path.stat().st_size} bytes)")
    finally:
        context.close()


def main() -> None:
    base_url = _require_env("E2E_BASE_URL").rstrip("/")
    output_dir = ROOT / "frontend" / "public" / "marketing"
    output_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--hide-scrollbars"],
        )

        # 1. Public pages in a clean, unauthenticated context.
        unauth_context = browser.new_context(
            viewport=DESKTOP_VIEWPORT,
            device_scale_factor=1,
            base_url=base_url,
            ignore_https_errors=True,
        )
        unauth_page = unauth_context.new_page()
        try:
            capture_unauth(unauth_page, output_dir)
        finally:
            unauth_context.close()

        # 2. Authenticated pages as Alex Kernel.
        desktop_context = browser.new_context(
            viewport=DESKTOP_VIEWPORT,
            device_scale_factor=1,
            base_url=base_url,
            ignore_https_errors=True,
        )
        page = desktop_context.new_page()

        try:
            login_as_alex(page)
            wait_for_welcome(page)
            profile_id, campaign_id = setup_data(page, browser, base_url)
            capture_desktop(page, output_dir, profile_id, campaign_id)
            capture_mobile(browser, base_url, output_dir, profile_id, campaign_id)
        finally:
            desktop_context.close()
            browser.close()

    print("\nAll marketing screenshots captured.")
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    main()

# Cleanup notes:
# The script intentionally leaves Alex Kernel's Cognito user, Account record,
# profiles, campaigns, orders, payment methods, and invites in place so the
# workflow can be re-run quickly.
#
# To remove only the Cognito user (data is preserved for re-capture):
#     bash scripts/delete-screenshot-user.sh
#
# To delete the user AND all associated data:
#   1. Log in to the app as Alex Kernel and go to Account Settings.
#   2. Scroll to "Delete Account" and follow the prompts. This removes the
#      DynamoDB Account record and all associated data via the backend.
#   3. Run scripts/delete-screenshot-user.sh to remove the Cognito user.
