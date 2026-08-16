"""Smoke tests for shared campaigns.

Covers the happy paths for listing, creating, editing, deactivating, and
joining a campaign via a shared-campaign short link.
"""

import re
import time
import urllib.parse

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.shared_campaigns_page import SharedCampaignsPage
from tests.e2e.utils.auth import login_as_owner

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _navigate_to_shared_campaigns(owner_page: Page) -> SharedCampaignsPage:
    """Navigate to the shared campaigns list as the owner."""
    shared = SharedCampaignsPage(owner_page)
    shared.goto()
    return shared


def _extract_profile_id(owner_page: Page) -> str:
    """Extract the first profile id from the dashboard."""
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    names = dashboard.get_profile_names()
    assert names, "Owner must have at least one seller profile"
    dashboard.click_profile(names[0])
    match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    assert match, f"Expected /scouts/{{id}}/campaigns URL; got: {owner_page.url}"
    return urllib.parse.unquote(match.group(1))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_shared_campaigns_list_loads(owner_page: Page) -> None:
    """The shared campaigns list page loads."""
    _navigate_to_shared_campaigns(owner_page)
    assert owner_page.get_by_text("My Shared Campaigns").first.is_visible(), (
        "Shared campaigns page header must be visible"
    )


@pytest.mark.smoke
def test_create_shared_campaign(owner_page: Page) -> None:
    """Create a shared campaign and verify it appears in the list."""
    shared = _navigate_to_shared_campaigns(owner_page)
    shared.click_create()

    campaign_name = f"E2E Shared Create {int(time.time())}"
    shared.create_shared_campaign(campaign_name=campaign_name)
    assert "/shared-campaigns" in owner_page.url, (
        f"Expected redirect to /shared-campaigns after creation; got: {owner_page.url}"
    )
    codes = shared.get_visible_codes()
    assert codes, "At least one shared campaign code must be visible after creation"


@pytest.mark.smoke
def test_edit_shared_campaign(owner_page: Page) -> None:
    """Create a shared campaign and edit its description."""
    shared = _navigate_to_shared_campaigns(owner_page)
    shared.click_create()

    campaign_name = f"E2E Shared Edit {int(time.time())}"
    shared.create_shared_campaign(campaign_name=campaign_name)
    codes = shared.get_visible_codes()
    assert codes, "A shared campaign code must exist to edit"
    code = codes[0]

    new_description = f"Updated description {int(time.time())}"
    shared.edit_description(code, new_description)
    assert shared.has_shared_campaign(code), "Edited shared campaign must still be visible"


@pytest.mark.smoke
def test_deactivate_shared_campaign(owner_page: Page) -> None:
    """Create a shared campaign and deactivate it."""
    shared = _navigate_to_shared_campaigns(owner_page)
    shared.click_create()

    campaign_name = f"E2E Shared Deactivate {int(time.time())}"
    shared.create_shared_campaign(campaign_name=campaign_name)
    codes = shared.get_visible_codes()
    assert codes, "A shared campaign code must exist to deactivate"
    code = codes[0]

    shared.deactivate_shared_campaign(code)
    # Status chip should now show "Inactive"
    row = shared._campaign_row(code)
    assert row.get_by_text("Inactive").first.is_visible(), (
        "Deactivated shared campaign must show Inactive status"
    )


@pytest.mark.smoke
def test_join_shared_campaign_creates_campaign(owner_page: Page, browser: Browser) -> None:
    """A shared campaign short link creates a campaign on the selected profile.

    This test:
      1. Creates a shared campaign as the owner.
      2. Opens a fresh browser context and logs in as the owner.
      3. Visits the short link, selects the first profile, and submits.
      4. Verifies the browser lands on a campaign detail page.
    """
    # Step 1: create shared campaign
    shared = _navigate_to_shared_campaigns(owner_page)
    shared.click_create()
    campaign_name = f"E2E Shared Join {int(time.time())}"
    shared.create_shared_campaign(campaign_name=campaign_name)
    codes = shared.get_visible_codes()
    assert codes, "A shared campaign code must be generated"
    code = codes[0]

    # Step 2: fresh context, same owner, join via short link
    join_context: BrowserContext = browser.new_context(ignore_https_errors=True)
    join_page: Page = join_context.new_page()
    try:
        login_as_owner(join_page)
        profile_id = _extract_profile_id(join_page)

        join_shared = SharedCampaignsPage(join_page)
        join_shared.join_shared_campaign(code, profile_id)
        assert "/campaigns/" in join_page.url, (
            f"Expected campaign detail URL after joining; got: {join_page.url}"
        )
    finally:
        join_context.close()
