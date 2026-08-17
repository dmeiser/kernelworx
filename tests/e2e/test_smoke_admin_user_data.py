"""Smoke tests for the admin user-data drill-down page.

Exercises issue #83: seed known contributor data (profile, catalog, campaign,
shared campaign, and share), then navigate to ``/admin/user-data/{accountId}``
and assert that specific rows appear in each relevant tab instead of accepting
all-empty results.
"""

import os
import re
import time
import urllib.parse

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e.pages.admin_page import AdminPage
from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.catalogs_page import CatalogsPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.manage_page import ManagePage
from tests.e2e.pages.share_page import SharePage
from tests.e2e.pages.shared_campaigns_page import SharedCampaignsPage
from tests.e2e.pages.user_data_page import UserDataPage
from tests.e2e.utils.auth import login_as_contributor, login_as_owner


def _extract_profile_id_from_url(url: str) -> str:
    """Return the raw profile ID from a ``/scouts/{id}/campaigns`` URL."""
    match = re.search(r"/scouts/([^/]+)/campaigns", url)
    assert match, f"Expected /scouts/{{id}}/campaigns in URL; got: {url}"
    return urllib.parse.unquote(match.group(1))


def _seed_contributor_data(browser: Browser) -> dict[str, str]:
    """Create a profile, catalog, campaign, shared campaign, and share as the contributor.

    Steps:

    1. Owner creates a disposable seller profile and transfers ownership to the
       contributor (the transfer mechanism requires a prior share, so we share
       then transfer).
    2. Contributor logs in and creates a private catalog.
    3. Contributor creates a campaign under the transferred profile using that
       catalog.
    4. Contributor creates a shared campaign from the same catalog.
    5. Contributor shares the profile with the owner so the Shares tab has a
       row; the returned invite code must be accepted by the owner in the test.

    Returns:
        Dictionary with keys ``profile_name``, ``profile_id``, ``catalog_name``,
        ``campaign_name``, ``shared_campaign_name``, ``shared_campaign_code``,
        and ``share_invite_code``.
    """
    owner_context: BrowserContext = browser.new_context(ignore_https_errors=True)
    owner_page: Page = owner_context.new_page()
    contributor_context: BrowserContext = browser.new_context(ignore_https_errors=True)
    contributor_page: Page = contributor_context.new_page()

    try:
        # Owner creates a disposable profile.
        login_as_owner(owner_page)
        dashboard = DashboardPage(owner_page)
        dashboard.goto()
        dashboard.wait_for_profiles_loaded()

        profile_name = f"E2E UserData {int(time.time())}"
        dashboard._create_scout_button().click()
        dialog = owner_page.get_by_role("dialog")
        owner_page.get_by_label("Scout Name").fill(profile_name)
        owner_page.get_by_role("button", name="Create Scout").click()
        expect(dialog).to_be_hidden(timeout=15_000)
        dashboard.wait_for_loading()
        dashboard.wait_for_profiles_loaded()
        assert profile_name in dashboard.get_profile_names(), (
            f"Created profile {profile_name!r} not visible on dashboard"
        )

        dashboard.click_profile(profile_name)
        profile_id = _extract_profile_id_from_url(owner_page.url)

        # Share with contributor, then transfer ownership.
        contributor_email = os.environ["TEST_CONTRIBUTOR_EMAIL"]
        share = SharePage(owner_page)
        share.goto(profile_id)
        share.create_invite("WRITE")
        invite_code = share.get_invite_link()
        assert invite_code, "Failed to generate WRITE invite for contributor"

        manage = ManagePage(owner_page)
        manage.goto(profile_id)
        manage.transfer_ownership(contributor_email)

        # Contributor accepts ownership and seeds data.
        login_as_contributor(contributor_page)
        contributor_dashboard = DashboardPage(contributor_page)
        contributor_dashboard.goto()
        contributor_dashboard.wait_for_profiles_loaded()
        assert profile_name in contributor_dashboard.get_profile_names(), (
            f"Transferred profile {profile_name!r} not visible to contributor"
        )
        contributor_dashboard.click_profile(profile_name)
        profile_id = _extract_profile_id_from_url(contributor_page.url)

        # Create a catalog as contributor.
        catalogs = CatalogsPage(contributor_page)
        catalogs.goto()
        catalog_name = f"E2E UserData Catalog {int(time.time())}"
        catalogs.create_catalog(
            catalog_name,
            products=[{"productName": "E2E UserData Popcorn", "price": 30}],
        )
        catalogs.switch_to_my_catalogs()
        assert catalogs.has_catalog(catalog_name), f"Created catalog {catalog_name!r} not visible to contributor"

        # Create a campaign under the transferred profile.
        campaigns = CampaignPage(contributor_page)
        campaigns.goto(profile_id)
        campaign_name = f"E2E UserData Campaign {int(time.time())}"
        campaigns.create_campaign_first_catalog(campaign_name, profile_id)

        # Create a shared campaign from the same catalog.
        shared = SharedCampaignsPage(contributor_page)
        shared.goto()
        shared.click_create()
        shared_campaign_name = f"E2E UserData Shared {int(time.time())}"
        shared.create_shared_campaign(catalog_name, shared_campaign_name)
        visible_codes = shared.get_visible_codes()
        assert visible_codes, "Shared campaign code must be visible after creation"
        shared_campaign_code = visible_codes[0]

        # Share the profile with owner so the Shares tab has a row.
        contrib_share = SharePage(contributor_page)
        contrib_share.goto(profile_id)
        contrib_share.create_invite("READ")
        share_invite_code = contrib_share.get_invite_link()
        assert share_invite_code, "Failed to generate READ invite for owner"

        return {
            "profile_name": profile_name,
            "profile_id": profile_id,
            "catalog_name": catalog_name,
            "campaign_name": campaign_name,
            "shared_campaign_name": shared_campaign_name,
            "shared_campaign_code": shared_campaign_code,
            "share_invite_code": share_invite_code,
        }
    finally:
        owner_context.close()
        contributor_context.close()


@pytest.mark.smoke
@pytest.mark.slow
def test_admin_user_data_tabs(owner_page: Page, browser: Browser) -> None:
    """Seed contributor data and assert specific rows appear in every relevant tab."""
    seeded = _seed_contributor_data(browser)

    # Owner accepts the share invite so the contributor's Shares tab can show it.
    owner_share = SharePage(owner_page)
    owner_share.accept_invite(seeded["share_invite_code"])
    owner_page.wait_for_url("**/scouts", timeout=15_000)

    # Navigate to the contributor's user-data page via admin search.
    contributor_email = os.environ["TEST_CONTRIBUTOR_EMAIL"]
    admin = AdminPage(owner_page)
    admin.goto()
    admin.switch_to_users()
    admin.search_user(contributor_email)

    contributor_cell = owner_page.get_by_role("cell", name=contributor_email).first
    expect(contributor_cell).to_be_visible(timeout=10_000)
    contributor_cell.click()
    owner_page.wait_for_url("**/admin/user-data/**", timeout=10_000)

    user_data = UserDataPage(owner_page)
    user_data.wait_for_loading()
    expect(owner_page.get_by_text("User Data Management").first).to_be_visible(timeout=15_000)
    assert "/admin/user-data/" in owner_page.url, f"Expected /admin/user-data/ in URL; got: {owner_page.url}"

    # Profiles tab: seeded profile must be present.
    expect(user_data._tabpanel_heading("Seller Profiles").first).to_be_visible(timeout=10_000)
    profile_names = user_data.get_profile_names()
    assert seeded["profile_name"] in profile_names, (
        f"Profiles tab must list seeded profile {seeded['profile_name']!r}; got: {profile_names}"
    )

    # Catalogs tab: seeded catalog must be present.
    user_data.switch_to_catalogs()
    expect(user_data._tabpanel_heading("Product Catalogs").first).to_be_visible(timeout=10_000)
    catalog_names = user_data.get_catalog_names()
    assert seeded["catalog_name"] in catalog_names, (
        f"Catalogs tab must list seeded catalog {seeded['catalog_name']!r}; got: {catalog_names}"
    )

    # Campaigns tab: select the seeded profile and assert the seeded campaign appears.
    user_data.switch_to_campaigns()
    expect(user_data._tabpanel_heading("Profile Campaigns").first).to_be_visible(timeout=10_000)
    user_data.select_profile_for_campaigns(seeded["profile_name"])
    campaign_names = user_data.get_campaign_names()
    assert seeded["campaign_name"] in campaign_names, (
        f"Campaigns tab must list seeded campaign {seeded['campaign_name']!r}; got: {campaign_names}"
    )

    # Shared Campaigns tab: seeded shared campaign must be present.
    user_data.switch_to_shared_campaigns()
    expect(user_data._tabpanel_heading("Shared Campaigns Created by User").first).to_be_visible(timeout=10_000)
    shared_names = user_data.get_shared_campaign_names()
    assert seeded["shared_campaign_name"] in shared_names, (
        f"Shared Campaigns tab must list seeded shared campaign {seeded['shared_campaign_name']!r}; got: {shared_names}"
    )

    # Shares tab: select the seeded profile and assert the owner's share appears.
    user_data.switch_to_shares()
    expect(user_data._tabpanel_heading("Profile Shares").first).to_be_visible(timeout=10_000)
    user_data.select_profile_for_shares(seeded["profile_name"])
    owner_email = os.environ["TEST_OWNER_EMAIL"]
    share_emails = user_data.get_share_emails()
    assert owner_email in share_emails, f"Shares tab must list owner's email {owner_email!r}; got: {share_emails}"
