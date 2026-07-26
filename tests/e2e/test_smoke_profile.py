"""Smoke tests for seller-profile visibility on the owner's dashboard.

These tests verify the most basic pre-condition for all other e2e tests: the
owner test user can see at least one seller profile after logging in.

Fixture dependency
------------------
``ensure_owner_profile`` (session-scoped, defined in ``conftest.py``) is
requested explicitly by every test here.  If the owner has no profiles in the
local (moto) environment, the fixture creates one via the *Create Scout*
dialog before any test in this module runs.
"""

import re
import urllib.parse
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.manage_page import ManagePage

# ---------------------------------------------------------------------------
# Local helpers (HTMX dialog selectors)
# ---------------------------------------------------------------------------


_DIALOG_SEL: str = "dialog#create-profile-dialog"
_NAME_INPUT_SEL: str = "dialog#create-profile-dialog input#sellerName"
_SUBMIT_BTN_NAME: str = "Create Scout"


def _create_scout_via_dialog(page: Page, profile_name: str) -> None:
    """Open the *Create Scout* dialog, fill *profile_name*, and submit."""
    dashboard = DashboardPage(page)
    dashboard._create_scout_button().first.click()
    page.locator(_NAME_INPUT_SEL).wait_for(state="visible", timeout=10_000)
    page.locator(_NAME_INPUT_SEL).fill(profile_name)
    page.locator(_DIALOG_SEL).get_by_role("button", name=_SUBMIT_BTN_NAME).click()
    # Wait for the new profile card to appear.
    page.locator("div.card[id^='profile-card-'] h3").filter(has_text=profile_name).first.wait_for(
        state="visible", timeout=15_000
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_profile_visible_after_login(owner_page: Page, ensure_owner_profile: str) -> None:
    """After login, the owner dashboard shows at least one seller-profile card."""
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
    """Creating a Scout via the dashboard UI adds it to the profile list."""
    profile_name = f"UI Create Test {uuid4().hex[:12]}"

    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    _create_scout_via_dialog(owner_page, profile_name)

    # Reload to get a clean, sortable DOM and confirm persistence.
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()

    names = dashboard.get_profile_names()
    assert profile_name in names, (
        f"Newly created profile '{profile_name}' was not found on the dashboard; visible names: {names}"
    )


@pytest.mark.smoke
def test_delete_profile(owner_page: Page) -> None:
    """A profile deleted via ManagePage no longer appears on the dashboard."""
    profile_name = f"Delete Me {uuid4().hex[:12]}"

    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    _create_scout_via_dialog(owner_page, profile_name)

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

    # Verify the profile is gone from the dashboard (DB-backed).
    names_after_delete: list[str] = []
    for _ in range(6):  # bounded polling
        dashboard.goto()
        dashboard.wait_for_loading()
        names_after_delete = dashboard.get_profile_names()
        if profile_name not in names_after_delete:
            break
        owner_page.wait_for_timeout(2_000)

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

    SKIPPED locally: the HTMX scout-management template does not render a
    shares table or *Transfer Ownership* button, and there is no real second
    Cognito user to accept a share.  The scenario is preserved as an explicit
    skip for traceability.
    """
    pytest.skip(
        "Transfer-ownership / share-acceptance flow requires a real second "
        "Cognito user and a shares table not rendered by the local HTMX "
        "scout-management template."
    )
