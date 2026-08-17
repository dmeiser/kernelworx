"""Smoke tests for seller-profile visibility on the owner's dashboard.

These tests verify the most basic pre-condition for all other e2e tests: the
owner test user can see at least one seller profile after logging in.

Fixture dependency
------------------
``ensure_owner_profile`` (session-scoped, defined in ``conftest.py``) is
requested explicitly by every test here.  If the owner has no profiles in the
dev environment, the fixture creates one via the *Create Scout* dialog before
any test in this module runs.
"""

import re
import urllib.parse
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.manage_page import ManagePage
from tests.e2e.pages.share_page import SharePage
from tests.e2e.utils.auth import login_as_readonly

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_profile_visible_after_login(owner_page: Page, ensure_owner_profile: str) -> None:
    """After login, the owner dashboard shows at least one seller-profile card.

    Relies on ``ensure_owner_profile`` to guarantee that a profile exists
    before the assertion, so this test passes on a freshly seeded dev
    environment as well as when profiles already exist.

    Asserts that:
    * At least one profile name heading (``<h3>``) is visible.
    * The expected profile name supplied by ``ensure_owner_profile`` appears
      in the list of visible names.

    Args:
        owner_page: Function-scoped Playwright page authenticated as owner.
        ensure_owner_profile: Session-scoped fixture; value is the seller name
            of the first profile guaranteed to exist.
    """
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()

    expect(dashboard._profile_headings().first).to_be_visible(timeout=10_000)

    names = dashboard.get_profile_names()
    assert names, "Owner dashboard must show at least one seller-profile card after login"
    assert ensure_owner_profile in names, (
        f"Expected profile '{ensure_owner_profile}' to appear on dashboard; found: {names}"
    )


@pytest.mark.smoke
def test_create_profile_via_ui(owner_page: Page) -> None:
    """Creating a Scout via the dashboard UI adds it to the profile list.

    Clicks the *Create Scout* button, fills the *Scout Name* dialog field with
    a timestamped name, submits, and asserts the new card is visible on the
    dashboard.

    Cleanup is handled by the session-scoped ``global_cleanup`` fixture — no
    explicit teardown is required here.

    Args:
        owner_page: Function-scoped Playwright page authenticated as owner.
    """
    profile_name = f"UI Create Test {uuid4().hex[:12]}"

    dashboard = DashboardPage(owner_page)
    dashboard.goto()

    dashboard._create_scout_button().click()
    dialog = owner_page.get_by_role("dialog")
    owner_page.get_by_label("Scout Name").fill(profile_name)
    owner_page.get_by_role("button", name="Create Scout").click()
    expect(dialog).to_be_hidden(timeout=15_000)

    dashboard.wait_for_loading()
    dashboard.wait_for_profiles_loaded()

    names = dashboard.get_profile_names()
    assert profile_name in names, (
        f"Newly created profile '{profile_name}' was not found on the dashboard; visible names: {names}"
    )


@pytest.mark.smoke
def test_delete_profile(owner_page: Page) -> None:
    """A profile deleted via ManagePage no longer appears on the dashboard.

    Creates a disposable profile via the dashboard dialog, navigates to its
    management page, deletes it, and confirms it has been removed from the
    profile list.

    Args:
        owner_page: Function-scoped Playwright page authenticated as owner.
    """
    profile_name = f"Delete Me {uuid4().hex[:12]}"

    dashboard = DashboardPage(owner_page)
    dashboard.goto()

    # Create the disposable profile.
    dashboard._create_scout_button().click()
    dialog = owner_page.get_by_role("dialog")
    owner_page.get_by_label("Scout Name").fill(profile_name)
    owner_page.get_by_role("button", name="Create Scout").click()
    expect(dialog).to_be_hidden(timeout=15_000)
    dashboard.wait_for_loading()
    dashboard.wait_for_profiles_loaded()

    names_after_create = dashboard.get_profile_names()
    assert profile_name in names_after_create, (
        f"'{profile_name}' not on dashboard after creation; visible: {names_after_create}"
    )

    # Navigate to campaigns page to extract profile_id from URL.
    dashboard.click_profile(profile_name)
    match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    assert match, f"Expected /scouts/{{id}}/campaigns after profile click; got: {owner_page.url}"
    profile_id = urllib.parse.unquote(match.group(1))

    # Delete via ManagePage.
    manage = ManagePage(owner_page)
    manage.goto(profile_id)
    manage.delete_profile()

    # Verify the profile is gone.
    #
    # In dev, profile deletion can be briefly stale due to eventual
    # consistency / client cache timing. Use bounded polling with fresh
    # navigation to avoid false negatives while still failing hard if the
    # profile truly remains.
    names_after_delete: list[str] = []
    for _ in range(12):  # up to ~60s (12 * 5s)
        dashboard.goto()
        dashboard.wait_for_loading()
        dashboard.wait_for_profiles_loaded()
        names_after_delete = dashboard.get_profile_names()
        if profile_name not in names_after_delete:
            break
        owner_page.wait_for_timeout(5_000)

    assert profile_name not in names_after_delete, (
        f"'{profile_name}' still visible on dashboard after deletion; visible: {names_after_delete}"
    )


@pytest.mark.smoke
def test_transfer_ownership_ui(
    owner_page: Page,
    browser: Browser,
    ensure_owner_profile: str,
) -> None:
    """Transfer Ownership button is visible on the manage page when shares exist.

    Creates a READ invite on the owner's first profile, accepts it with the
    readonly test user (in a separate browser context), then verifies the
    *Transfer Ownership* button appears in the share table row.

    The button is clicked but the ``window.confirm`` dialog is auto-dismissed
    by Playwright (no handler → dismiss), so no transfer is completed.
    The test then asserts the manage page URL is still active, confirming the
    UI flow did not crash.

    Note:
        ``owner_page`` and a fresh ``readonly`` page each need their own browser
        context.  A separate context is created via the session-scoped
        ``browser`` fixture rather than requesting ``readonly_page`` which shares
        the same function-scoped ``page`` instance as ``owner_page``.

    Args:
        owner_page: Function-scoped Playwright page authenticated as owner.
        browser: Session-scoped Playwright Browser used to spin up an isolated
            context for the readonly test user.
        ensure_owner_profile: Ensures the owner has at least one profile and
            yields the first profile name.
    """
    # ------------------------------------------------------------------
    # 1.  Get the profile_id for ensure_owner_profile.
    # ------------------------------------------------------------------
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()

    dashboard.click_profile(ensure_owner_profile)
    match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    assert match, f"Expected /scouts/{{id}}/campaigns after profile click; got: {owner_page.url}"
    profile_id = urllib.parse.unquote(match.group(1))

    # ------------------------------------------------------------------
    # 2.  Create a READ invite on this specific profile.
    # ------------------------------------------------------------------
    owner_share = SharePage(owner_page)
    owner_share.goto(profile_id)
    owner_share.create_invite("READ")
    invite_code = owner_share.get_invite_link()
    assert invite_code, "Failed to generate a READ invite code for the test profile"

    # ------------------------------------------------------------------
    # 3.  Accept the invite in an isolated readonly browser context.
    # ------------------------------------------------------------------
    readonly_context: BrowserContext = browser.new_context(ignore_https_errors=True)
    try:
        readonly_pg: Page = readonly_context.new_page()
        login_as_readonly(readonly_pg)
        readonly_share = SharePage(readonly_pg)
        readonly_share.accept_invite(invite_code)
    finally:
        readonly_context.close()

    # ------------------------------------------------------------------
    # 4.  Navigate back as owner and verify Transfer Ownership is visible.
    # ------------------------------------------------------------------
    manage = ManagePage(owner_page)
    manage.goto(profile_id)
    assert manage.transfer_ownership_button_is_visible(), (
        "Transfer Ownership button not found after creating a share on the profile"
    )

    # Click Transfer Ownership; Playwright auto-dismisses the window.confirm.
    manage.click_transfer_ownership()

    # After auto-dismissal the page should remain on the manage route.
    assert "/manage" in owner_page.url, (
        f"Expected to stay on manage page after dismissing confirm; got: {owner_page.url}"
    )
