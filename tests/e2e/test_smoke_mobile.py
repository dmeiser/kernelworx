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
from tests.e2e.pages.public_pages import PublicPages
from tests.e2e.utils.mobile import navigate_to_first_orders_page, use_mobile_viewport


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
def test_mobile_landing_page_renders(page: Page) -> None:
    """The public landing page renders the hero and primary CTA on a mobile viewport."""
    use_mobile_viewport(page)
    public = PublicPages(page)
    public.goto_landing()
    assert public.landing_is_visible(), "Landing page hero heading must render on mobile viewport"
    public.expect_landing_primary_cta()


@pytest.mark.smoke
def test_mobile_orders_list_renders(owner_page: Page, ensure_owner_profile: str) -> None:
    """The campaign orders list renders on a mobile viewport."""
    use_mobile_viewport(owner_page)
    order_page = navigate_to_first_orders_page(owner_page)
    assert order_page._new_order_button().is_visible(), (
        "Orders list must render with the *New Order* action on mobile viewport"
    )


@pytest.mark.smoke
@pytest.mark.slow
def test_mobile_order_editor_submission(owner_page: Page, ensure_owner_profile: str) -> None:
    """Create an order from the order editor on a mobile viewport."""
    use_mobile_viewport(owner_page)
    order_page = navigate_to_first_orders_page(owner_page)
    customer_name = "Mobile Order Customer"
    order_page.create_order_first_product(customer_name, qty=1)
    assert order_page.has_order(customer_name), (
        f"'{customer_name}' must appear in the orders table after mobile submission"
    )


@pytest.mark.smoke
def test_mobile_hamburger_menu(owner_page: Page) -> None:
    """The AppLayout mobile hamburger menu opens the navigation drawer."""
    use_mobile_viewport(owner_page)
    BasePage(owner_page).navigate("/home")
    DashboardPage(owner_page).wait_for_loading()

    menu_button = owner_page.get_by_role("button", name="open drawer")
    expect(menu_button).to_be_visible(timeout=10_000)

    menu_button.click()
    drawer_item = owner_page.get_by_role("button", name="My Scouts")
    expect(drawer_item).to_be_visible(timeout=10_000)
