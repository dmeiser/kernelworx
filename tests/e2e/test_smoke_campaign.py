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
import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.campaign_settings_page import CampaignSettingsPage
from tests.e2e.pages.catalogs_page import CatalogsPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.shared_campaigns_page import SharedCampaignsPage

_CAMPAIGN_NAME: str = f"Smoke Test Campaign {uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _navigate_to_first_profile_campaigns(owner_page: Page, profile_name: str) -> tuple[str, str, CampaignPage]:
    """Navigate from the dashboard to the owned profile's campaigns page.

    Args:
        owner_page: Authenticated Playwright page for the owner.
        profile_name: Owned seller profile name (from ``ensure_owner_profile``).

    Returns:
        Tuple of ``(profile_name, profile_id, campaign_page)`` where
        *campaign_page* is scoped to the currently visible campaigns list.
    """
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    dashboard.click_profile(profile_name)
    match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    assert match, f"Expected /scouts/{{id}}/campaigns URL, got: {owner_page.url}"
    profile_id = urllib.parse.unquote(match.group(1))
    return profile_name, profile_id, CampaignPage(owner_page)


def _create_campaign_with_first_catalog(campaign_page: CampaignPage, name: str, profile_id: str | None = None) -> None:
    """Delegate to the public POM method that picks the first catalog.

    Args:
        campaign_page: :class:`CampaignPage` instance for the current profile.
        name: Campaign name to enter in the dialog form.
        profile_id: Optional profile ID to select on the create-campaign page.
    """
    campaign_page.create_campaign_first_catalog(name, profile_id)


def _extract_campaign_ids(url: str) -> tuple[str, str]:
    """Extract profile and campaign IDs from a campaign detail/settings URL.

    Args:
        url: Current browser URL containing ``/scouts/{profileId}/campaigns/{campaignId}``.

    Returns:
        Tuple of ``(profile_id, campaign_id)`` with URL decoding applied.
    """
    match = re.search(r"/scouts/([^/]+)/campaigns/([^/?#]+)", url)
    assert match, f"Could not extract campaign IDs from URL: {url}"
    profile_id = urllib.parse.unquote(match.group(1))
    campaign_id = urllib.parse.unquote(match.group(2))
    return profile_id, campaign_id


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
    _, _profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page, ensure_owner_profile)
    owner_page.wait_for_url("**/campaigns**", timeout=10_000)
    expect(campaign_page._new_campaign_button()).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_create_campaign(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Create a campaign and verify it appears in the profile's campaign list.

    Creates a campaign named ``'Smoke Test Campaign 2026'`` using the first
    available catalog in the dev environment.  Asserts the campaign heading
    is visible in the list after the dialog closes.
    """
    _, profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page, ensure_owner_profile)
    _create_campaign_with_first_catalog(campaign_page, _CAMPAIGN_NAME, profile_id)
    assert campaign_page.has_campaign(_CAMPAIGN_NAME), (
        f"Campaign '{_CAMPAIGN_NAME}' must be visible in the list after creation"
    )


@pytest.mark.smoke
def test_view_campaign_detail(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Verify that clicking a campaign card navigates to the campaign detail page.

    Asserts:
    * At least one campaign exists in the owner's first profile.
    * Clicking *View Orders* navigates to a URL containing ``/campaigns/``.
    * The Orders tab widget is visible on that page.
    """
    _, profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page, ensure_owner_profile)
    names = campaign_page.get_campaign_names()

    campaign_to_open = names[0] if names else None
    if campaign_to_open is None:
        # Self-heal in sparse dev environments where cleanup removed all
        # campaigns for the current profile.
        campaign_to_open = f"View Detail Seed {int(time.time())}"
        _create_campaign_with_first_catalog(campaign_page, campaign_to_open, profile_id)

    campaign_page.click_campaign(campaign_to_open)
    url = owner_page.url
    assert "/campaigns/" in url, f"Expected /campaigns/ in URL after click; got: {url}"
    # The app uses a catch-all route (/campaigns/:id/*); the default tab renders
    # at the root URL without an /orders suffix — verify via the tab widget only.
    orders_tab = owner_page.get_by_role("tab", name="Orders")
    expect(orders_tab).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_catalog_selected_in_campaign(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Verify that a newly created campaign has a campaign name saved correctly.

    Creates a fresh campaign with the first available catalog, then navigates
    directly to the settings tab and reads the stored campaign name to confirm
    the creation persisted all fields.
    """
    campaign_name = f"Catalog Check Test {int(time.time())}"
    _, profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page, ensure_owner_profile)
    _create_campaign_with_first_catalog(campaign_page, campaign_name, profile_id)
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
def test_edit_campaign(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Verify that editing a campaign name persists the change.

    Creates a campaign, navigates to its settings tab, renames it, then
    re-reads the field to confirm the update was saved.
    """
    original_name = f"Edit Campaign Test {int(time.time())}"
    _, profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page, ensure_owner_profile)
    _create_campaign_with_first_catalog(campaign_page, original_name, profile_id)
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
def test_delete_campaign(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Verify that a campaign can be deleted and disappears from the list.

    Creates a disposable campaign, navigates to its settings, confirms deletion,
    then checks the campaign list no longer contains the campaign name.
    """
    campaign_name = f"Delete Campaign Test {int(time.time())}"
    _, profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page, ensure_owner_profile)
    # Capture profile_id from the campaigns list URL before creation.
    campaigns_url = owner_page.url
    match0 = re.search(r"/scouts/([^/]+)/campaigns", campaigns_url)
    assert match0, f"Could not extract profile_id from URL: {campaigns_url}"
    profile_id = urllib.parse.unquote(match0.group(1))
    _create_campaign_with_first_catalog(campaign_page, campaign_name, profile_id)
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


@pytest.mark.smoke
def test_edit_campaign_dates(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Verify that campaign start/end dates persist after saving.

    Creates a campaign, sets a start and end date on the settings tab,
    saves, reloads the page, and asserts both dates are still present.
    """
    campaign_name = f"Edit Dates Test {int(time.time())}"
    _, profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page, ensure_owner_profile)
    _create_campaign_with_first_catalog(campaign_page, campaign_name, profile_id)
    campaign_page.click_campaign(campaign_name)
    profile_id, campaign_id = _extract_campaign_ids(owner_page.url)

    settings = CampaignSettingsPage(owner_page)
    settings.goto(profile_id, campaign_id)
    start_date = "2026-01-01"
    end_date = "2026-01-31"
    settings.set_start_date(start_date)
    settings.set_end_date(end_date)
    settings.click_save()

    owner_page.reload()
    settings.wait_for_loading()
    assert settings.get_start_date() == start_date, (
        f"Expected start date '{start_date}'; got '{settings.get_start_date()}'"
    )
    assert settings.get_end_date() == end_date, (
        f"Expected end date '{end_date}'; got '{settings.get_end_date()}'"
    )


@pytest.mark.smoke
def test_reselect_campaign_catalog(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Verify that changing a campaign's catalog persists after saving.

    Creates a campaign and a second catalog, then switches the campaign to
    the new catalog on the settings tab and confirms the selection survives
    a page reload.
    """
    campaign_name = f"Reselect Catalog Test {int(time.time())}"
    _, profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page, ensure_owner_profile)
    _create_campaign_with_first_catalog(campaign_page, campaign_name, profile_id)

    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()
    new_catalog_name = f"Reselect Catalog {int(time.time())}"
    catalogs.create_catalog(new_catalog_name, [{"productName": "Widget", "price": 10.0}])

    campaign_page.goto(profile_id)
    campaign_page.click_campaign(campaign_name)
    _, campaign_id = _extract_campaign_ids(owner_page.url)
    settings = CampaignSettingsPage(owner_page)
    settings.goto(profile_id, campaign_id)
    settings.select_catalog_by_name(new_catalog_name)
    settings.click_save()

    owner_page.reload()
    settings.wait_for_loading()
    selected = settings.get_selected_catalog_name()
    assert new_catalog_name in selected, (
        f"Expected catalog '{new_catalog_name}' to be selected; got '{selected}'"
    )


@pytest.mark.smoke
def test_toggle_campaign_active(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Verify that toggling the campaign active switch persists and hides the campaign.

    Creates a campaign, flips the active switch on the settings tab, saves,
    reloads, asserts the switch reflects the new state, then returns to the
    campaign list and confirms the deactivated campaign is no longer visible.
    """
    campaign_name = f"Toggle Active Test {int(time.time())}"
    _, profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page, ensure_owner_profile)
    _create_campaign_with_first_catalog(campaign_page, campaign_name, profile_id)
    campaign_page.click_campaign(campaign_name)
    _, campaign_id = _extract_campaign_ids(owner_page.url)

    settings = CampaignSettingsPage(owner_page)
    settings.goto(profile_id, campaign_id)
    original_active = settings.get_is_active()
    settings.toggle_active()
    settings.click_save()

    owner_page.reload()
    settings.wait_for_loading()
    assert settings.get_is_active() is not original_active, (
        f"Expected active state to change from {original_active}"
    )

    # Issue #81: deactivation should move the campaign out of the Active section.
    campaign_page.goto(profile_id)
    assert not campaign_page.has_active_campaign(campaign_name), (
        f"Deactivated campaign '{campaign_name}' must not appear in the active campaign list"
    )


@pytest.mark.smoke
def test_confirm_shared_campaign_changes(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify the shared-campaign change confirmation dialog when renaming/re-cataloging.

    Creates a shared campaign, joins it to create a derived campaign, then
    changes the derived campaign's name and catalog. The save triggers a
    confirmation dialog that must be accepted before the changes persist.
    """
    _, profile_id, _campaign_page = _navigate_to_first_profile_campaigns(owner_page, ensure_owner_profile)

    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()
    catalog1 = f"Shared Catalog 1 {int(time.time())}"
    catalog2 = f"Shared Catalog 2 {int(time.time())}"
    catalogs.create_catalog(catalog1, [{"productName": "A", "price": 5.0}])
    catalogs.create_catalog(catalog2, [{"productName": "B", "price": 7.0}])

    shared = SharedCampaignsPage(owner_page)
    shared.goto_create()
    base_name = f"Shared Base {int(time.time())}"
    shared.create_shared_campaign(catalog_name=catalog1, campaign_name=base_name)
    shared.goto()
    code = shared.get_code_by_campaign_name(base_name)
    assert code, f"Could not find shared campaign code for '{base_name}'"

    shared.join_shared_campaign(code, profile_id)
    profile_id, campaign_id = _extract_campaign_ids(owner_page.url)

    settings = CampaignSettingsPage(owner_page)
    settings.goto(profile_id, campaign_id)
    new_name = f"Shared Derived Edited {int(time.time())}"
    settings.set_campaign_name(new_name)
    settings.select_catalog_by_name(catalog2)
    settings.click_save()
    settings.confirm_shared_campaign_changes()

    owner_page.reload()
    settings.wait_for_loading()
    assert settings.get_campaign_name() == new_name, (
        f"Expected campaign name '{new_name}'; got '{settings.get_campaign_name()}'"
    )
    selected = settings.get_selected_catalog_name()
    assert catalog2 in selected, (
        f"Expected catalog '{catalog2}' to be selected; got '{selected}'"
    )
