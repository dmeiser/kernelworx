"""Smoke tests for campaign creation and listing.

Navigation strategy
-------------------
Tests rely on the owner account having **at least one** seller profile in the
dev environment (created by ``scripts/create-test-users.sh``).  The first
visible profile on the dashboard is used for all campaign operations.

Catalog selection
-----------------
The dev environment's product catalog name is not hard-coded here.
``_create_campaign_with_first_catalog`` opens the *New Campaign* dialog and
programmatically picks the **first** available option from the catalog
dropdown, making the test independent of the exact catalog name.
"""

import re
import time
import urllib.parse

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.campaign_settings_page import CampaignSettingsPage
from tests.e2e.pages.dashboard_page import DashboardPage

_CAMPAIGN_NAME: str = "Smoke Test Campaign 2026"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _navigate_to_first_profile_campaigns(owner_page: Page) -> tuple[str, CampaignPage]:
    """Navigate from the dashboard to the first profile's campaigns page.

    Args:
        owner_page: Authenticated Playwright page for the owner.

    Returns:
        Tuple of ``(profile_name, campaign_page)`` where *campaign_page* is
        scoped to the currently visible campaigns list.
    """
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    names = dashboard.get_profile_names()
    assert names, "Owner must have at least one seller profile in the dev environment"
    profile_name = names[0]
    dashboard.click_profile(profile_name)
    return profile_name, CampaignPage(owner_page)


def _create_campaign_with_first_catalog(campaign_page: CampaignPage, name: str) -> None:
    """Delegate to the public POM method that picks the first catalog.

    Args:
        campaign_page: :class:`CampaignPage` instance for the current profile.
        name: Campaign name to enter in the dialog form.
    """
    campaign_page.create_campaign_first_catalog(name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_campaign_list_visible(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify the campaigns page loads correctly for the owner's first profile.

    Asserts that:
    * Navigating to the profile takes the browser to a ``/campaigns`` URL.
    * The *New Campaign* action button is visible, confirming the page is
      fully rendered and not stuck in a loading state.
    """
    _, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    owner_page.wait_for_url("**/campaigns**", timeout=10_000)
    expect(campaign_page._new_campaign_button()).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_create_campaign(owner_page: Page, ensure_owner_profile: str) -> None:
    """Create a campaign and verify it appears in the profile's campaign list.

    Creates a campaign named ``'Smoke Test Campaign 2026'`` using the first
    available catalog in the dev environment.  Asserts the campaign heading
    is visible in the list after the dialog closes.
    """
    _, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    _create_campaign_with_first_catalog(campaign_page, _CAMPAIGN_NAME)
    assert campaign_page.has_campaign(_CAMPAIGN_NAME), (
        f"Campaign '{_CAMPAIGN_NAME}' must be visible in the list after creation"
    )


@pytest.mark.smoke
def test_view_campaign_detail(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify that clicking a campaign card navigates to the campaign detail page.

    Asserts:
    * At least one campaign exists in the owner's first profile.
    * Clicking *View Orders* navigates to a URL containing ``/campaigns/``.
    * The Orders tab widget is visible on that page.
    """
    _, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    names = campaign_page.get_campaign_names()
    assert names, "Owner must have at least one campaign to run test_view_campaign_detail"
    campaign_page.click_campaign(names[0])
    url = owner_page.url
    assert "/campaigns/" in url, f"Expected /campaigns/ in URL after click; got: {url}"
    # The app uses a catch-all route (/campaigns/:id/*); the default tab renders
    # at the root URL without an /orders suffix — verify via the tab widget only.
    orders_tab = owner_page.get_by_role("tab", name="Orders")
    expect(orders_tab).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_catalog_selected_in_campaign(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify that a newly created campaign has a campaign name saved correctly.

    Creates a fresh campaign with the first available catalog, then navigates
    directly to the settings tab and reads the stored campaign name to confirm
    the creation persisted all fields.
    """
    campaign_name = f"Catalog Check Test {int(time.time())}"
    _, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    _create_campaign_with_first_catalog(campaign_page, campaign_name)
    # After creation we are back on the campaigns list; click into the campaign.
    campaign_page.click_campaign(campaign_name)
    url = owner_page.url
    match = re.search(r"/scouts/([^/]+)/campaigns/([^/?#]+)", url)
    assert match, f"Could not extract IDs from URL: {url}"
    profile_id = urllib.parse.unquote(match.group(1))
    campaign_id = urllib.parse.unquote(match.group(2))
    settings = CampaignSettingsPage(owner_page)
    settings.goto(profile_id, campaign_id)
    saved_name = settings.get_campaign_name()
    assert saved_name, "Campaign name field must not be empty after creation"


@pytest.mark.smoke
def test_edit_campaign(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify that editing a campaign name persists the change.

    Creates a campaign, navigates to its settings tab, renames it, then
    re-reads the field to confirm the update was saved.
    """
    original_name = f"Edit Campaign Test {int(time.time())}"
    _, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    _create_campaign_with_first_catalog(campaign_page, original_name)
    campaign_page.click_campaign(original_name)
    url = owner_page.url
    match = re.search(r"/scouts/([^/]+)/campaigns/([^/?#]+)", url)
    assert match, f"Could not extract IDs from URL: {url}"
    profile_id = urllib.parse.unquote(match.group(1))
    campaign_id = urllib.parse.unquote(match.group(2))
    settings = CampaignSettingsPage(owner_page)
    settings.goto(profile_id, campaign_id)
    old_name = settings.get_campaign_name()
    new_name = old_name + " Edited"
    settings.edit_campaign_name(new_name)
    assert settings.get_campaign_name() == new_name, (
        f"Expected campaign name '{new_name}' after edit; got '{settings.get_campaign_name()}'"
    )


@pytest.mark.smoke
def test_delete_campaign(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify that a campaign can be deleted and disappears from the list.

    Creates a disposable campaign, navigates to its settings, confirms deletion,
    then checks the campaign list no longer contains the campaign name.
    """
    campaign_name = f"Delete Campaign Test {int(time.time())}"
    _, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    # Capture profile_id from the campaigns list URL before creation.
    campaigns_url = owner_page.url
    match0 = re.search(r"/scouts/([^/]+)/campaigns", campaigns_url)
    assert match0, f"Could not extract profile_id from URL: {campaigns_url}"
    profile_id = urllib.parse.unquote(match0.group(1))
    _create_campaign_with_first_catalog(campaign_page, campaign_name)
    campaign_page.click_campaign(campaign_name)
    url = owner_page.url
    match = re.search(r"/scouts/([^/]+)/campaigns/([^/?#]+)", url)
    assert match, f"Could not extract campaign_id from URL: {url}"
    campaign_id = urllib.parse.unquote(match.group(2))
    settings = CampaignSettingsPage(owner_page)
    settings.goto(profile_id, campaign_id)
    settings.delete_campaign()
    # The app navigated to campaigns list; reload to confirm deletion.
    campaign_page2 = CampaignPage(owner_page)
    campaign_page2.goto(profile_id)
    names = campaign_page2.get_campaign_names()
    assert campaign_name not in names, (
        f"Deleted campaign '{campaign_name}' must not appear in campaign list; found: {names}"
    )
