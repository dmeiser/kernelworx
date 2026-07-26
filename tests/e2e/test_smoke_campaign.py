"""Smoke tests for campaign creation and listing.

Navigation strategy
-------------------
Tests rely on the owner account having **at least one** seller profile in the
local (moto) environment (created by the ``ensure_owner_profile`` session
fixture).  The first visible profile on the dashboard is used for all campaign
operations.

Catalog selection
-----------------
The HTMX create-campaign dialog has no catalog selector (the React page did);
``create_campaign_first_catalog`` simply fills the campaign name and submits.
"""

import re
import time
import urllib.parse
import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage

_CAMPAIGN_NAME: str = f"Smoke Test Campaign {uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _navigate_to_first_profile_campaigns(owner_page: Page) -> tuple[str, str, CampaignPage]:
    """Navigate from the dashboard to the first profile's campaigns page.

    Args:
        owner_page: Authenticated Playwright page for the owner.

    Returns:
        Tuple of ``(profile_name, profile_id, campaign_page)``.
    """
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    names = dashboard.get_profile_names()
    assert names, "Owner must have at least one seller profile in the local environment"
    profile_name = names[0]
    dashboard.click_profile(profile_name)
    match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    assert match, f"Expected /scouts/{{id}}/campaigns URL, got: {owner_page.url}"
    profile_id = urllib.parse.unquote(match.group(1))
    return profile_name, profile_id, CampaignPage(owner_page)


def _create_campaign_with_first_catalog(campaign_page: CampaignPage, name: str, profile_id: str | None = None) -> None:
    """Delegate to the public POM method that creates a campaign by name."""
    campaign_page.create_campaign_first_catalog(name, profile_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_campaign_list_visible(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify the campaigns page loads correctly for the owner's first profile."""
    _, _profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    owner_page.wait_for_url("**/campaigns**", timeout=10_000)
    expect(campaign_page._new_campaign_button()).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_create_campaign(owner_page: Page, ensure_owner_profile: str) -> None:
    """Create a campaign and verify it appears in the profile's campaign list."""
    _, profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    _create_campaign_with_first_catalog(campaign_page, _CAMPAIGN_NAME, profile_id)
    assert campaign_page.has_campaign(_CAMPAIGN_NAME), (
        f"Campaign '{_CAMPAIGN_NAME}' must be visible in the list after creation"
    )


@pytest.mark.smoke
def test_view_campaign_detail(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify that clicking a campaign card navigates to the campaign orders page.

    Asserts:
    * At least one campaign exists in the owner's first profile (seeded if not).
    * Clicking *View Orders* navigates to a URL containing ``/campaigns/``.
    * The orders page is visible (orders tab link / "New Order" action).
    """
    _, profile_id, campaign_page = _navigate_to_first_profile_campaigns(owner_page)
    names = campaign_page.get_campaign_names()

    campaign_to_open = names[0] if names else None
    if campaign_to_open is None:
        # Self-heal in sparse environments by creating a campaign on demand.
        campaign_to_open = f"View Detail Seed {int(time.time())}"
        _create_campaign_with_first_catalog(campaign_page, campaign_to_open, profile_id)

    campaign_page.click_campaign(campaign_to_open)
    url = owner_page.url
    assert "/campaigns/" in url, f"Expected /campaigns/ in URL after click; got: {url}"
    # The orders page renders a "New Order" action and an "Orders" tab link.
    new_order = owner_page.get_by_role("link", name="New Order").or_(owner_page.get_by_role("button", name="New Order"))
    expect(new_order.first).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_catalog_selected_in_campaign(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify that a newly created campaign has a campaign name saved correctly.

    SKIPPED locally: the HTMX redesign has no campaign settings page (the
    orders page links to ``/campaigns/{id}/settings`` but no route/handler
    serves it), so the stored campaign name cannot be read back via the
    settings form.  Campaign-name persistence is instead covered by
    ``test_create_campaign`` (the card heading shows the name).
    """
    pytest.skip(
        "Campaign settings page is not implemented in the HTMX redesign; "
        "cannot read back the saved campaign name via the settings form locally."
    )


@pytest.mark.smoke
def test_edit_campaign(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify that editing a campaign name persists the change.

    SKIPPED locally: the HTMX redesign has no campaign settings / edit page.
    """
    pytest.skip("Campaign settings / edit page is not implemented in the HTMX redesign.")


@pytest.mark.smoke
def test_delete_campaign(owner_page: Page, ensure_owner_profile: str) -> None:
    """Verify that a campaign can be deleted and disappears from the list.

    SKIPPED locally: the HTMX redesign does not expose a campaign-delete UI
    (campaign cards only have a *View Orders* link; the campaign-delete
    handler exists but is not wired to any button).
    """
    pytest.skip(
        "Campaign-delete UI is not exposed in the HTMX redesign (no delete "
        "button on the campaign card or a settings page)."
    )
