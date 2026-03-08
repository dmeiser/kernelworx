"""Smoke tests for the /settings page."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.base_page import BasePage

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_settings_page_loads(owner_page: Page) -> None:
    """The /settings page loads and displays a top-level heading.

    Navigates to ``/settings`` as the authenticated owner and asserts that:
    * The URL contains ``"/settings"``.
    * At least one ``role="heading"`` element is visible (the ``<h1>``
      rendered by ``<Typography variant="h4" component="h1">``).

    Args:
        owner_page: Function-scoped Playwright page authenticated as owner.
    """
    base = BasePage(owner_page)
    base.navigate("/settings")
    base.wait_for_loading()

    assert "/settings" in owner_page.url, (
        f"Expected URL to contain '/settings'; got: {owner_page.url}"
    )

    heading = owner_page.get_by_role("heading").first
    expect(heading).to_be_visible(timeout=10_000)
