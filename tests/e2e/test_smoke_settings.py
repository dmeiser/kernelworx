"""Smoke tests for the /account/settings page.

The HTMX redesign serves the user-settings page at ``/account/settings``
(``user_settings.html``).  The base sidebar links to ``/settings`` (a separate
route not wired in the local server); this test navigates directly to the
implemented ``/account/settings`` route.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.base_page import BasePage

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_settings_page_loads(owner_page: Page) -> None:
    """The /account/settings page loads and displays a top-level heading.

    Navigates to ``/account/settings`` as the authenticated owner and asserts
    that the URL contains ``/account/settings`` and a top-level heading
    (``User Settings``) is visible.
    """
    base = BasePage(owner_page)
    base.navigate("/account/settings")
    base.wait_for_loading()

    assert "/account/settings" in owner_page.url, f"Expected URL to contain '/account/settings'; got: {owner_page.url}"

    heading = owner_page.get_by_role("heading").first
    expect(heading).to_be_visible(timeout=10_000)
