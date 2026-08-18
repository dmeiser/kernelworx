"""Mobile viewport helpers for E2E smoke tests."""

import re
import time
import urllib.parse

from playwright.sync_api import Page, ViewportSize

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.order_page import OrderPage

#: Viewport matching a modern mobile phone (iPhone 14 dimensions).
MOBILE_VIEWPORT: ViewportSize = {"width": 390, "height": 844}


def use_mobile_viewport(page: Page) -> None:
    """Resize the browser page to a mobile viewport.

    Also sets a mobile user-agent so any UA-based logic sees a phone.

    Args:
        page: Playwright page to resize.
    """
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.context.set_extra_http_headers(
        {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            )
        }
    )


def navigate_to_first_orders_page(page: Page) -> OrderPage:
    """Navigate to the orders list for the first available profile and campaign.

    Starts from the dashboard, selects the first seller profile, then the first
    campaign, and finally loads ``/scouts/{profileId}/campaigns/{campaignId}/orders``.
    If the selected profile has no campaigns, a one-off campaign is seeded using
    the first available catalog so mobile order tests can run in freshly cleaned
    environments.

    Args:
        page: Authenticated Playwright page.

    Returns:
        OrderPage focused on the orders list of the first campaign found.
    """
    dashboard = DashboardPage(page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    profile_names = dashboard.get_profile_names()
    assert profile_names, "At least one seller profile is required for mobile order tests"

    dashboard.click_profile(profile_names[0])
    campaign_page = CampaignPage(page)
    campaign_page.wait_for_loading()
    campaign_names = campaign_page.get_campaign_names()

    if not campaign_names:
        # Seed a campaign so the order editor/list can be exercised.
        profile_match = re.search(r"/scouts/([^/]+)/campaigns", page.url)
        assert profile_match, f"Expected /scouts/{{id}}/campaigns URL, got: {page.url}"
        profile_id = urllib.parse.unquote(profile_match.group(1))
        seed_name = f"Mobile Seed Campaign {int(time.time())}"
        campaign_page.create_campaign_first_catalog(seed_name, profile_id)

        # Campaign list visibility can lag briefly after creation in fresh
        # environments, so poll with fresh navigations before giving up.
        campaign_names: list[str] = []
        for _ in range(12):  # up to ~60s
            campaign_page.goto(profile_id)
            campaign_names = campaign_page.get_campaign_names()
            if campaign_names:
                break
            page.wait_for_timeout(5_000)

        assert campaign_names, "Failed to seed campaign for mobile order tests"

    campaign_page.click_campaign(campaign_names[0])

    ids_match = re.search(r"/scouts/([^/]+)/campaigns/([^/?#]+)", page.url)
    assert ids_match, f"Expected /scouts/{{id}}/campaigns/{{id}} URL, got: {page.url}"
    profile_id = urllib.parse.unquote(ids_match.group(1))
    campaign_id = urllib.parse.unquote(ids_match.group(2))

    order_page = OrderPage(page)
    order_page.goto(profile_id, campaign_id)
    return order_page
