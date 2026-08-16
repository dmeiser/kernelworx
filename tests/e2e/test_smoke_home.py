"""Smoke tests for the logged-in home page."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.home_page import HomePage


@pytest.mark.smoke
def test_home_page_loads(owner_page: Page) -> None:
    """The authenticated home page renders the welcome heading."""
    home = HomePage(owner_page)
    home.goto()
    assert home.is_visible(), "Welcome back heading must be visible on /home"


@pytest.mark.smoke
def test_home_page_quick_actions(owner_page: Page) -> None:
    """The home page shows all four quick-action tiles."""
    home = HomePage(owner_page)
    home.goto()
    for title in ["My Scouts", "Payment Methods", "Catalogs", "Shared Campaigns"]:
        tile = owner_page.get_by_role("heading", name=title).first
        expect(tile).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_home_page_navigates_to_scouts(owner_page: Page) -> None:
    """Clicking the My Scouts tile navigates to /scouts."""
    home = HomePage(owner_page)
    home.goto()
    home.click_my_scouts()
    assert "/scouts" in owner_page.url, f"Expected /scouts after tile click; got: {owner_page.url}"


@pytest.mark.smoke
def test_home_page_navigates_to_catalogs(owner_page: Page) -> None:
    """Clicking the Catalogs tile navigates to /catalogs."""
    home = HomePage(owner_page)
    home.goto()
    home.click_catalogs()
    assert "/catalogs" in owner_page.url, f"Expected /catalogs after tile click; got: {owner_page.url}"
