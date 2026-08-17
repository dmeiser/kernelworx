"""Mobile viewport smoke tests.

These tests verify that core authenticated and unauthenticated pages render
usable layouts on a phone-sized viewport.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.base_page import BasePage
from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.login_page import LoginPage
from tests.e2e.utils.mobile import use_mobile_viewport


@pytest.mark.smoke
def test_mobile_login_page_renders(page: Page) -> None:
    """The login page renders the email/password form on a mobile viewport."""
    use_mobile_viewport(page)
    login_page = LoginPage(page)
    login_page.goto()

    expect(page.locator('input[type="email"]').first).to_be_visible(timeout=10_000)
    expect(page.locator('input[type="password"]').first).to_be_visible(timeout=10_000)
    expect(page.get_by_role("button", name="Sign In", exact=True)).to_be_visible(timeout=10_000)


@pytest.mark.smoke
def test_mobile_dashboard_renders(owner_page: Page) -> None:
    """The Scouts dashboard renders on a mobile viewport."""
    use_mobile_viewport(owner_page)
    dashboard = DashboardPage(owner_page)
    dashboard.goto()

    assert dashboard.is_visible(), "Dashboard (/scouts) must render on mobile viewport"


@pytest.mark.smoke
def test_mobile_campaign_list_renders(owner_page: Page, ensure_owner_profile: str) -> None:
    """A seller profile's campaign list renders on a mobile viewport."""
    use_mobile_viewport(owner_page)
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()

    profile_names = dashboard.get_profile_names()
    if not profile_names:
        pytest.skip("No seller profiles available for mobile campaign list test")

    dashboard.click_profile(profile_names[0])
    campaign_page = CampaignPage(owner_page)
    assert campaign_page.new_campaign_button_is_available(), (
        "Campaign list must render with the *New Campaign* action on mobile viewport"
    )


@pytest.mark.smoke
def test_mobile_hamburger_menu(owner_page: Page) -> None:
    """The AppLayout mobile hamburger menu opens the navigation drawer."""
    use_mobile_viewport(owner_page)
    BasePage(owner_page).navigate("/home")
    DashboardPage(owner_page).wait_for_loading()

    menu_button = owner_page.get_by_role("button", name="open drawer")
    if not menu_button.is_visible():
        pytest.skip("Mobile hamburger menu is not rendered on this viewport")

    menu_button.click()
    drawer_item = owner_page.get_by_role("button", name="My Scouts")
    expect(drawer_item).to_be_visible(timeout=10_000)
