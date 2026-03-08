"""Smoke tests for the campaign Reports & Exports tab."""

import re
import urllib.parse

import pytest
from playwright.sync_api import Page

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.reports_page import ReportsPage


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_profile_id_from_url(url: str) -> str:
    """Extract the profile ID from a ``/scouts/{id}/…`` URL.

    Args:
        url: Full browser URL string.

    Returns:
        URL-decoded profile identifier.

    Raises:
        AssertionError: When the URL does not contain the expected pattern.
    """
    match = re.search(r"/scouts/([^/]+)", url)
    assert match, f"Could not extract profile_id from URL: {url}"
    return urllib.parse.unquote(match.group(1))


def _get_campaign_id_from_url(url: str) -> str:
    """Extract the campaign ID from a ``/scouts/{id}/campaigns/{id}/…`` URL.

    Args:
        url: Full browser URL string.

    Returns:
        URL-decoded campaign identifier.

    Raises:
        AssertionError: When the URL does not contain the expected pattern.
    """
    match = re.search(r"/scouts/[^/]+/campaigns/([^/?#]+)", url)
    assert match, f"Could not extract campaign_id from URL: {url}"
    return urllib.parse.unquote(match.group(1))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_campaign_reports_tab_loads(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify the Reports & Exports tab loads and shows the expected heading.

    Navigation strategy:

    1. Open the owner's dashboard and click the first profile.
    2. Use the first existing campaign, or create one if the list is empty.
    3. Click *View Orders* to land on the campaign detail page and capture the
       campaign ID from the URL.
    4. Navigate directly to the ``/reports`` tab.
    5. Assert the URL ends with ``/reports`` and that an ``<h5>`` containing
       "Reports" is visible.
    """
    # Step 1 – navigate to first profile's campaigns.
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    profile_names = dashboard.get_profile_names()
    assert profile_names, "Owner must have at least one seller profile"
    dashboard.click_profile(profile_names[0])
    owner_page.wait_for_url("**/campaigns**", timeout=10_000)
    profile_id = _get_profile_id_from_url(owner_page.url)
    campaign_page = CampaignPage(owner_page)

    # Step 2 – ensure at least one campaign exists.
    campaign_names = campaign_page.get_campaign_names()
    if not campaign_names:
        campaign_page.create_campaign_first_catalog("Reports Smoke Test Campaign")
        campaign_names = campaign_page.get_campaign_names()
    assert campaign_names, "Need at least one campaign to test the reports tab"

    # Step 3 – click into the campaign to capture its ID.
    campaign_page.click_campaign(campaign_names[0])
    campaign_id = _get_campaign_id_from_url(owner_page.url)

    # Step 4 – navigate to the reports tab.
    reports = ReportsPage(owner_page)
    reports.goto(profile_id, campaign_id)

    # Step 5 – assertions.
    assert "/reports" in owner_page.url, f"Expected /reports in URL; got: {owner_page.url}"
    assert reports.heading_is_visible(), "Expected h5 containing 'Reports' to be visible on the reports tab"
