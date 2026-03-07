"""Smoke tests for the profile-sharing flow.

Flow overview
-------------
1. ``test_create_invite``  – owner generates a WRITE invite for the first profile.
2. ``test_accept_share``   – contributor redeems the invite code.
3. ``test_shared_profile_visible_to_contributor`` – contributor can view the
   campaigns page for the now-shared profile.
4. ``test_revoke_share``   – owner revokes access; contributor is removed from
   the shares table.

State sharing
-------------
``test_create_invite`` stores ``invite_code`` and ``profile_id`` in
``_module_state`` (a module-scoped fixture).  Subsequent tests read from it.
Tests that cannot find a required key call ``pytest.skip`` with a clear reason
instead of raising an ``AssertionError``.

Test ordering
-------------
These tests are designed to run in file order (pytest default).  Randomising
the order will cause skips for tests that depend on earlier state.

Two browser contexts
--------------------
``owner_page`` and ``contributor_page`` are both function-scoped fixtures that
wrap the same pytest-playwright ``page`` fixture.  **Do not request both in the
same test function** — they would share one Playwright page.  Each test here
uses *one* role at a time; cross-role verification is deferred to successive
tests that run with a fresh page fixture.
"""

import os
import re
import urllib.parse
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.order_page import OrderPage
from tests.e2e.pages.share_page import SharePage
from tests.e2e.utils.auth import login_as_contributor

# ---------------------------------------------------------------------------
# Module-scoped state fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _module_state() -> dict[str, str]:
    """Mutable dict shared across all tests in this module.

    Keys populated at runtime:
    * ``"invite_code"``  – set by ``test_create_invite``
    * ``"profile_id"``   – set by ``test_create_invite``
    """
    return {}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _navigate_to_share_management(owner_page: Page) -> tuple[SharePage, str]:
    """Navigate to the share-management page for the owner's first profile.

    Steps:
    1. Dashboard → click first seller profile → URL contains profile_id.
    2. Extract and decode profile_id from the URL.
    3. Navigate to ``/scouts/{profile_id}/manage`` via :class:`SharePage`.

    Args:
        owner_page: Authenticated Playwright page for the owner.

    Returns:
        Tuple of ``(share_page, profile_id)``.
    """
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    profiles = dashboard.get_profile_names()
    assert profiles, "Owner must have at least one seller profile"

    dashboard.click_profile(profiles[0])
    # After clicking, URL is /scouts/{profile_id}/campaigns
    match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    assert match, f"Expected /scouts/{{id}}/campaigns URL after profile click, got: {owner_page.url}"
    profile_id = urllib.parse.unquote(match.group(1))

    share_page = SharePage(owner_page)
    share_page.goto(profile_id)
    return share_page, profile_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_create_invite(owner_page: Page, _module_state: dict[str, str]) -> None:
    """Owner generates a WRITE invite for the first profile; code is non-empty.

    Stores ``invite_code`` and ``profile_id`` in ``_module_state`` so that
    ``test_accept_share``, ``test_shared_profile_visible_to_contributor``, and
    ``test_revoke_share`` can re-use them without duplicating the setup.
    """
    share_page, profile_id = _navigate_to_share_management(owner_page)
    share_page.create_invite("WRITE")
    invite_code = share_page.get_invite_link()

    assert invite_code, "Invite code must be a non-empty string after generation"

    _module_state["invite_code"] = invite_code
    _module_state["profile_id"] = profile_id


@pytest.mark.smoke
def test_accept_share(contributor_page: Page, _module_state: dict[str, str]) -> None:
    """Contributor redeems the invite code; a success alert is shown.

    Uses the contributor's fresh browser context (separate from the owner).
    Verifies that the acceptance alert is visible and does not contain an
    error message, indicating the share was granted.
    """
    invite_code = _module_state.get("invite_code", "")
    if not invite_code:
        pytest.skip("invite_code not set — ensure test_create_invite ran first")

    share_page = SharePage(contributor_page)
    share_page.accept_invite(invite_code)

    alert = contributor_page.get_by_role("alert").first
    expect(alert).to_be_visible(timeout=15_000)
    alert_text = alert.inner_text()
    assert alert_text, "A non-empty alert must appear after accepting the invite"
    assert "error" not in alert_text.lower(), f"Invite acceptance should not show an error; alert reads: '{alert_text}'"


@pytest.mark.smoke
def test_shared_profile_visible_to_contributor(contributor_page: Page, _module_state: dict[str, str]) -> None:
    """Contributor can view the shared profile's campaigns page.

    Navigates the contributor directly to the profile's campaigns URL.
    A successful page load (URL contains ``/campaigns``) confirms the
    contributor has been granted READ/WRITE access.
    """
    profile_id = _module_state.get("profile_id", "")
    if not profile_id:
        pytest.skip("profile_id not set — ensure test_create_invite ran first")

    campaign_page = CampaignPage(contributor_page)
    campaign_page.goto(profile_id)

    contributor_page.wait_for_url("**/campaigns**", timeout=15_000)
    assert "/campaigns" in contributor_page.url, "Contributor must be able to load the shared profile's campaigns page"


@pytest.mark.smoke
def test_revoke_share(owner_page: Page, _module_state: dict[str, str]) -> None:
    """Owner revokes the contributor's access; contributor is removed from shares table.

    Navigates to the share-management page and calls :meth:`SharePage.revoke_access`.
    After revocation the contributor's email must **not** appear in the
    *Current Access* table, confirming the share record was deleted.
    """
    profile_id = _module_state.get("profile_id", "")
    if not profile_id:
        pytest.skip("profile_id not set — ensure test_create_invite ran first")

    contributor_email = os.environ["TEST_CONTRIBUTOR_EMAIL"]

    share_page = SharePage(owner_page)
    share_page.goto(profile_id)

    # Guard: only attempt revocation if the share actually exists
    if not share_page.has_shared_access(contributor_email):
        pytest.skip(f"'{contributor_email}' is not in the shares table; ensure test_accept_share ran first")

    share_page.revoke_access(contributor_email)

    assert not share_page.has_shared_access(contributor_email), (
        "Contributor must be removed from the shares table after revocation"
    )


@pytest.mark.smoke
def test_readonly_share_cannot_modify(readonly_page: Page, ensure_readonly_share: None) -> None:
    """READ-only shared user cannot create or modify campaigns on a shared profile.

    Navigates to the read-only user's dashboard and clicks the first visible
    shared profile.  Asserts that the *New Campaign* button is absent or
    disabled, confirming that READ permission does not grant write access.

    The ``ensure_readonly_share`` fixture (session-scoped) guarantees that the
    readonly user has an active READ share to the owner's first profile before
    this test runs, so no profiles-missing skip is necessary.
    """
    dashboard = DashboardPage(readonly_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()

    profiles = dashboard.get_profile_names()
    assert profiles, (
        "Readonly user must have at least one visible profile; "
        "ensure_readonly_share should have created the READ share"
    )

    # Navigate to the campaigns page for the first visible profile.
    dashboard.click_profile(profiles[0])

    match = re.search(r"/scouts/([^/]+)/campaigns", readonly_page.url)
    assert match, f"Expected /scouts/{{id}}/campaigns URL after profile click; got: {readonly_page.url}"

    campaign_page = CampaignPage(readonly_page)

    assert not campaign_page.new_campaign_button_is_available(), (
        "READ-only share must not grant campaign creation access: "
        "'New Campaign' button must be absent or disabled for a read-only user"
    )


@pytest.mark.smoke
@pytest.mark.slow
def test_write_share_contributor_can_create_order(
    owner_page: Page,
    browser: Browser,
    ensure_owner_profile: str,
) -> None:
    """A WRITE-share contributor can create an order on the shared profile's campaign.

    Self-contained test that:

    1. Generates a fresh WRITE invite as the owner.
    2. Redeems it as the contributor in an isolated browser context.
    3. Creates an order on the first campaign of the shared profile.
    4. Asserts the order is visible in the orders table.
    5. Revokes the contributor's access as cleanup.

    Args:
        owner_page: Authenticated Playwright page for the owner.
        browser: Session-scoped Playwright Browser used to open an isolated
            contributor context without interfering with owner_page.
        ensure_owner_profile: Session fixture ensuring the owner has at least
            one seller profile before this test runs.
    """
    # ------------------------------------------------------------------
    # Owner: navigate to dashboard and extract first profile_id
    # ------------------------------------------------------------------
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    profiles = dashboard.get_profile_names()
    assert profiles, "Owner must have at least one seller profile"

    dashboard.click_profile(profiles[0])
    match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    assert match, f"Expected /scouts/{{id}}/campaigns after clicking profile; got: {owner_page.url}"
    profile_id = urllib.parse.unquote(match.group(1))

    # Ensure there is at least one campaign on the shared profile.
    campaign_page_owner = CampaignPage(owner_page)
    campaign_page_owner.goto(profile_id)
    campaign_page_owner.wait_for_loading()
    if not campaign_page_owner.get_campaign_names():
        campaign_page_owner.create_campaign_first_catalog(f"Share Seed Campaign {uuid4().hex[:10]}")

    # Campaign list visibility can lag briefly after creation.
    owner_campaigns: list[str] = []
    for _ in range(12):  # up to ~60s
        campaign_page_owner.goto(profile_id)
        campaign_page_owner.wait_for_loading()
        owner_campaigns = campaign_page_owner.get_campaign_names()
        if owner_campaigns:
            break
        owner_page.wait_for_timeout(5_000)
    assert owner_campaigns, "Shared profile must have at least one campaign before creating a WRITE invite"

    # ------------------------------------------------------------------
    # Owner: generate a WRITE invite
    # ------------------------------------------------------------------
    share_page = SharePage(owner_page)
    share_page.goto(profile_id)
    share_page.create_invite("WRITE")
    invite_code = share_page.get_invite_link()
    assert invite_code, "WRITE invite code must be non-empty"

    # ------------------------------------------------------------------
    # Contributor (isolated context): accept invite and create an order
    # ------------------------------------------------------------------
    contributor_context: BrowserContext = browser.new_context(ignore_https_errors=True)
    contributor_pg: Page = contributor_context.new_page()
    try:
        login_as_contributor(contributor_pg)
        SharePage(contributor_pg).accept_invite(invite_code)

        campaign_page_contrib = CampaignPage(contributor_pg)
        campaigns: list[str] = []
        for _ in range(12):  # up to ~60s after invite redemption
            campaign_page_contrib.goto(profile_id)
            campaign_page_contrib.wait_for_loading()
            campaigns = campaign_page_contrib.get_campaign_names()
            if campaigns:
                break
            contributor_pg.wait_for_timeout(5_000)
        assert campaigns, "Shared profile must have at least one campaign"

        campaign_page_contrib.click_campaign(campaigns[0])
        url_match = re.search(r"/scouts/([^/]+)/campaigns/([^/?#]+)", contributor_pg.url)
        assert url_match, f"Expected /scouts/id/campaigns/id after clicking campaign; got: {contributor_pg.url}"
        camp_id = urllib.parse.unquote(url_match.group(2))

        order_page_contrib = OrderPage(contributor_pg)
        order_page_contrib.goto(profile_id, camp_id)
        order_page_contrib.create_order_first_product("Contributor Order Test", 1)
        assert order_page_contrib.has_order("Contributor Order Test"), (
            "Contributor with WRITE access must be able to create orders on the shared profile"
        )
    finally:
        contributor_context.close()

    # ------------------------------------------------------------------
    # Owner: revoke contributor access as cleanup
    # ------------------------------------------------------------------
    contributor_email: str = os.environ["TEST_CONTRIBUTOR_EMAIL"]
    share_page.goto(profile_id)
    if share_page.has_shared_access(contributor_email):
        share_page.revoke_access(contributor_email)
