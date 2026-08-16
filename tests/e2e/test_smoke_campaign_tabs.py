"""Smoke tests for campaign detail tabs.

These tests verify that the Orders, Summary, Reports, and Settings tabs are
reachable for a campaign owned by the test user.
"""

import re
import time
import urllib.parse

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.campaign_settings_page import CampaignSettingsPage
from tests.e2e.pages.dashboard_page import DashboardPage

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _navigate_to_first_profile_campaigns(owner_page: Page) -> tuple[str, CampaignPage]:
    """Navigate from the dashboard to the first profile's campaigns page."""
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    names = dashboard.get_profile_names()
    assert names, "Owner must have at least one seller profile in the dev environment"
    dashboard.click_profile(names[0])
    match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    assert match, f"Expected /scouts/{{id}}/campaigns URL, got: {owner_page.url}"
    profile_id = urllib.parse.unquote(match.group(1))
    return profile_id, CampaignPage(owner_page)


def _create_or_pick_campaign(owner_page: Page, profile_id: str, campaign_page: CampaignPage) -> tuple[str, str]:
    """Return a campaign id and name, creating one if the profile has none."""
    names = campaign_page.get_campaign_names()
    if not names:
        campaign_name = f"Tabs Seed Campaign {int(time.time())}"
        campaign_page.create_campaign_first_catalog(campaign_name, profile_id)
        names = campaign_page.get_campaign_names()
    assert names, "Profile must have at least one campaign for tab tests"
    campaign_page.click_campaign(names[0])
    url = owner_page.url
    match = re.search(r"/scouts/([^/]+)/campaigns/([^/?#]+)", url)
    assert match, f"Could not extract campaign_id from URL: {url}"
    campaign_id = urllib.parse.unquote(match.group(2))
    return campaign_id, names[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_orders_tab_visible(owner_page: Page, ensure_owner_profile: str) -> None:
    """The Orders tab is visible on the campaign detail page."""
    profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    _create_or_pick_campaign(owner_page, profile_id, campaign_page)

    orders_tab = owner_page.get_by_role("tab", name="Orders")
    expect(orders_tab).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_summary_tab_visible(owner_page: Page, ensure_owner_profile: str) -> None:
    """The Summary tab renders campaign summary content."""
    profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    _create_or_pick_campaign(owner_page, profile_id, campaign_page)

    owner_page.get_by_role("tab", name="Summary").click()
    owner_page.wait_for_url("**/summary", timeout=10_000)
    heading = owner_page.get_by_role("heading").first
    expect(heading).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_reports_tab_visible(owner_page: Page, ensure_owner_profile: str) -> None:
    """The Reports tab renders campaign reports content."""
    profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    _create_or_pick_campaign(owner_page, profile_id, campaign_page)

    owner_page.get_by_role("tab", name="Reports").click()
    owner_page.wait_for_url("**/reports", timeout=10_000)
    heading = owner_page.get_by_role("heading").first
    expect(heading).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_settings_tab_visible(owner_page: Page, ensure_owner_profile: str) -> None:
    """The Settings tab shows the campaign name input."""
    profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    campaign_id, _ = _create_or_pick_campaign(owner_page, profile_id, campaign_page)

    settings = CampaignSettingsPage(owner_page)
    settings.goto(profile_id, campaign_id)
    name = settings.get_campaign_name()
    assert name, "Campaign name field must be visible and non-empty on the Settings tab"
