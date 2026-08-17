"""Smoke tests for the shared-campaign reports page.

Covers issue #84: create and join a shared campaign to generate data, then
navigate to ``/campaign-reports`` and verify Unit Summary, Seller Report, and
Order Details render.
"""

import re
import time
import urllib.parse
import uuid

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e.pages.campaign_reports_page import CampaignReportsPage
from tests.e2e.pages.order_page import OrderPage
from tests.e2e.pages.shared_campaigns_page import SharedCampaignsPage
from tests.e2e.utils.auth import login_as_owner

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _unique_campaign_name(base: str) -> str:
    """Return a campaign name whose first four characters are unique.

    The shared-campaign code uses the first four characters of the campaign
    name as an abbreviation, so reuse of the same prefix causes a code
    collision in the dev environment.
    """
    prefix = f"E{uuid.uuid4().hex[:3].upper()}"
    return f"{prefix} {base} {int(time.time())}"


def _code_for_campaign_name(page: Page, campaign_name: str) -> str:
    """Return the short code for the visible row matching *campaign_name*."""
    row = page.get_by_role("row").filter(has_text=campaign_name)
    expect(row).to_be_visible(timeout=10_000)
    code = row.get_by_role("cell").filter(
        has_text=re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)+$")
    ).inner_text()
    return code


def _get_profile_id_from_url(url: str) -> str:
    """Extract the profile ID from a ``/scouts/{id}/…`` URL."""
    match = re.search(r"/scouts/([^/]+)", url)
    assert match, f"Could not extract profile_id from URL: {url}"
    return urllib.parse.unquote(match.group(1))


def _get_campaign_id_from_url(url: str) -> str:
    """Extract the campaign ID from a ``/scouts/{id}/campaigns/{id}/…`` URL."""
    match = re.search(r"/scouts/[^/]+/campaigns/([^/?#]+)", url)
    assert match, f"Could not extract campaign_id from URL: {url}"
    return urllib.parse.unquote(match.group(1))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.slow
def test_campaign_reports_generate_and_views(owner_page: Page, browser: Browser, ensure_owner_profile: str) -> None:
    """Create a shared campaign, join it, add an order, and verify reports."""
    # Step 1 — create a shared campaign as the owner.
    shared = SharedCampaignsPage(owner_page)
    shared.goto()
    shared.click_create()
    campaign_name = _unique_campaign_name("Unit Report")
    shared.create_shared_campaign(campaign_name=campaign_name)
    code = _code_for_campaign_name(owner_page, campaign_name)

    # Step 2 — join the shared campaign in a fresh context and capture IDs.
    join_context: BrowserContext = browser.new_context(ignore_https_errors=True)
    join_page: Page = join_context.new_page()
    try:
        login_as_owner(join_page)
        join_shared = SharedCampaignsPage(join_page)
        join_shared.join_shared_campaign(code)
        assert "/campaigns/" in join_page.url, (
            f"Expected campaign detail URL after joining; got: {join_page.url}"
        )
        profile_id = _get_profile_id_from_url(join_page.url)
        campaign_id = _get_campaign_id_from_url(join_page.url)

        # Step 3 — create an order so the unit report has seller data.
        order_page = OrderPage(join_page)
        order_page.goto(profile_id, campaign_id)
        customer_name = f"Unit Report {int(time.time())}"
        order_page.create_order_first_product(customer_name, qty=1)
    finally:
        join_context.close()

    # Step 4 — generate the campaign report.
    reports = CampaignReportsPage(owner_page)
    reports.goto()
    assert reports.is_visible(), "Shared Campaign Reports heading must be visible"
    reports.select_campaign_by_code(code)
    assert reports.can_generate_report(), "Generate Report button must be enabled after selection"
    reports.generate_report()

    # Step 5 — assert Unit Summary renders.
    assert reports.report_header_is_visible(), "Report header card must be visible after generation"
    assert reports.unit_summary_is_visible(), "Unit Summary cards and Top Sellers table must render"

    # Step 6 — assert Seller Report and Order Details tables render.
    reports.switch_to_seller_report()
    assert reports.seller_report_is_visible(), "Seller Report section and table must render"

    reports.switch_to_order_details()
    assert reports.order_details_is_visible(), "Order Details section and table must render"
