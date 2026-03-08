"""Smoke tests for order creation and list visibility.

Navigation strategy
-------------------
Both tests navigate from:
  Dashboard → first profile → first campaign → orders page.

The owner account must have at least one campaign when these tests run.
Running ``tests/e2e/test_smoke_campaign.py`` first (which creates
*Smoke Test Campaign 2026*) satisfies this requirement in a freshly seeded env.

Product selection
-----------------
The exact product name is not hard-coded.  ``_submit_order_first_product``
opens the product combobox and selects the **first** available option,
making the tests independent of catalog contents.

Payment method
--------------
The order editor defaults to *Cash* when the Cash payment method is available
(confirmed from ``OrderEditorPage.tsx`` — ``getDefaultPaymentMethodName``
prefers Cash).  No explicit payment selection is needed in these tests.

Test ordering
-------------
``test_order_appears_in_list`` relies on the order created by
``test_create_order``.  State is shared via the ``_module_state`` fixture
(module-scoped dict) so the second test can navigate directly to the campaign
that was used during creation — rather than guessing the ``first`` campaign
in the UI, which may be wrong if orphaned campaigns exist.
"""

import re
import time
import urllib.parse
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.campaign_page import CampaignPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.order_page import OrderPage

_CUSTOMER_NAME: str = "Jane Smith"
_ORDER_QTY: str = "2"


# ---------------------------------------------------------------------------
# Module-scoped state fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _module_state() -> dict[str, str]:
    """Mutable dict shared across all tests in this module.

    Keys populated at runtime:
    * ``"profile_id"``   – set by ``test_create_order``
    * ``"campaign_id"``  – set by ``test_create_order``
    * ``"customer_name"``– set by ``test_create_order``
    """
    return {}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract_profile_and_campaign_ids(url: str) -> tuple[str, str]:
    """Parse *profile_id* and *campaign_id* from a campaign URL.

    Expected URL shape: ``/scouts/{profileId}/campaigns/{campaignId}[/...]``

    Args:
        url: Full browser URL string.

    Returns:
        Tuple of ``(profile_id, campaign_id)`` with URL-decoding applied.
    """
    match = re.search(r"/scouts/([^/]+)/campaigns/([^/?#]+)", url)
    assert match, f"Expected /scouts/{{id}}/campaigns/{{id}} URL, got: {url}"
    return urllib.parse.unquote(match.group(1)), urllib.parse.unquote(match.group(2))


def _navigate_to_orders(owner_page: Page) -> tuple[OrderPage, str, str]:
    """Navigate from dashboard to the first profile's first campaign orders page.

    Steps:
    1. Dashboard → click first seller profile.
    2. Campaigns list → click first campaign.
    3. Extract profile_id / campaign_id from URL.
    4. Navigate directly to orders sub-page and return :class:`OrderPage`.

    Args:
        owner_page: Authenticated Playwright page for the owner.

    Returns:
        3-tuple ``(order_page, profile_id, campaign_id)`` where *order_page* is
        focused on the orders for the navigated campaign.
    """
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_loading()
    profiles = dashboard.get_profile_names()
    if not profiles:
        # Self-heal sparse environments by creating a profile on demand.
        profile_name = f"Order Seed Profile {uuid4().hex[:10]}"
        dashboard._create_scout_button().click()
        dialog = owner_page.get_by_role("dialog")
        owner_page.get_by_label("Scout Name").fill(profile_name)
        owner_page.get_by_role("button", name="Create Scout").click()
        expect(dialog).to_be_hidden(timeout=15_000)
        dashboard.wait_for_loading()
        profiles = dashboard.get_profile_names()

    assert profiles, "Owner must have at least one seller profile"

    campaign_page = CampaignPage(owner_page)
    chosen_profile = None
    campaigns: list[str] = []
    for profile_name in profiles:
        dashboard.goto()
        dashboard.wait_for_profiles_loaded()
        dashboard.click_profile(profile_name)
        campaign_page.wait_for_loading()
        campaigns = campaign_page.get_campaign_names()
        if campaigns:
            chosen_profile = profile_name
            break
    if chosen_profile is None:
        # No campaigns found on any profile; seed one for orders smoke tests.
        dashboard.goto()
        dashboard.wait_for_loading()
        dashboard.click_profile(profiles[0])
        campaign_page.wait_for_loading()
        profile_match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
        assert profile_match, f"Expected /scouts/{{id}}/campaigns URL, got: {owner_page.url}"
        seed_profile_id = urllib.parse.unquote(profile_match.group(1))
        seed_name = f"Order Seed Campaign {int(time.time())}"
        campaign_page.create_campaign_first_catalog(seed_name)
        # Poll with fresh navigations; campaign visibility can lag briefly.
        campaigns = []
        for _ in range(12):  # up to ~60s
            campaign_page.goto(seed_profile_id)
            campaigns = campaign_page.get_campaign_names()
            if campaigns:
                break
            owner_page.wait_for_timeout(5_000)
        assert campaigns, "Failed to seed campaign for order smoke tests"
        chosen_profile = profiles[0]

    campaign_page.click_campaign(campaigns[0])

    profile_id, campaign_id = _extract_profile_and_campaign_ids(owner_page.url)
    order_page = OrderPage(owner_page)
    order_page.goto(profile_id, campaign_id)
    return order_page, profile_id, campaign_id


def _submit_order_first_product(order_page: OrderPage, customer_name: str, qty: str) -> None:
    """Delegate to the public POM method that picks the first available product.

    Args:
        order_page: :class:`OrderPage` current on the orders list.
        customer_name: Customer full name to enter.
        qty: Quantity string for the single line item.
    """
    order_page.create_order_first_product(customer_name, int(qty))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.slow
def test_create_order(owner_page: Page, _module_state: dict[str, str], ensure_owner_profile: str) -> None:
    """Create an order for Jane Smith with 2 units of the first available product.

    Verifies that after submitting the order editor the app returns to the
    orders list and *Jane Smith* is visible as a table entry — confirming the
    order was persisted and the UI reflects it.

    Stores ``profile_id``, ``campaign_id``, and ``customer_name`` in
    ``_module_state`` for use by ``test_order_appears_in_list``.
    """
    order_page, profile_id, campaign_id = _navigate_to_orders(owner_page)
    _submit_order_first_product(order_page, _CUSTOMER_NAME, _ORDER_QTY)
    assert order_page.has_order(_CUSTOMER_NAME), f"'{_CUSTOMER_NAME}' must appear in the orders table after creation"
    _module_state["profile_id"] = profile_id
    _module_state["campaign_id"] = campaign_id
    _module_state["customer_name"] = _CUSTOMER_NAME


@pytest.mark.smoke
@pytest.mark.slow
def test_order_appears_in_list(owner_page: Page, _module_state: dict[str, str], ensure_owner_profile: str) -> None:
    """Verify the order created by test_create_order persists in the orders list.

    Navigates directly to the campaign stored in ``_module_state`` (set by
    ``test_create_order``) rather than guessing the first campaign in the UI,
    which guards against orphaned campaigns from previous runs giving false
    results.  Skips cleanly when ``_module_state`` keys are missing so the
    test suite does not fail when run in isolation.

    Uses a fresh ``owner_page`` fixture (new browser context) to confirm that
    the DynamoDB-backed order record survives a full page reload.
    """
    campaign_id = _module_state.get("campaign_id", "")
    profile_id = _module_state.get("profile_id", "")
    if not campaign_id or not profile_id:
        pytest.skip("campaign_id/profile_id not set — ensure test_create_order ran first")

    customer_name = _module_state.get("customer_name", _CUSTOMER_NAME)
    order_page = OrderPage(owner_page)
    order_page.goto(profile_id, campaign_id)

    cell = owner_page.get_by_role("cell", name=customer_name)
    expect(cell.first).to_be_visible(timeout=10_000)
    assert order_page.has_order(customer_name), (
        f"'{customer_name}' must be visible in the orders table on a fresh page load"
    )


@pytest.mark.smoke
@pytest.mark.slow
def test_edit_order(owner_page: Page, ensure_owner_profile: str) -> None:
    """Create an order, edit it via the edit button, and verify the updated name.

    Creates a fresh *Edit Target Customer* order, clicks the first (edit) icon
    button on that row, changes the customer name to *Edited Customer*, submits
    with the *Update Order* button, and asserts the new name appears in the
    orders list.

    Args:
        owner_page: Authenticated Playwright page for the owner.
        ensure_owner_profile: Session fixture ensuring at least one profile exists.
    """
    order_page, _profile_id, _campaign_id = _navigate_to_orders(owner_page)
    order_page.create_order_first_product("Edit Target Customer", 1)
    assert order_page.has_order("Edit Target Customer"), (
        "'Edit Target Customer' must appear before attempting to edit it"
    )

    row = owner_page.get_by_role("row").filter(has_text="Edit Target Customer")
    row.get_by_role("button").first.click()
    owner_page.wait_for_url("**/orders/**/edit", timeout=10_000)

    heading = owner_page.get_by_role("heading", name="Edit Order")
    expect(heading.first).to_be_visible(timeout=10_000)

    owner_page.get_by_label("Customer Name").fill("Edited Customer")
    owner_page.get_by_role("button", name="Update Order").click()
    owner_page.wait_for_url("**/orders", timeout=15_000)
    order_page.wait_for_loading()

    assert order_page.has_order("Edited Customer"), (
        "'Edited Customer' must appear in the orders table after editing"
    )


@pytest.mark.smoke
@pytest.mark.slow
def test_delete_order(owner_page: Page, ensure_owner_profile: str) -> None:
    """Create an order, delete it via the delete button, and verify it disappears.

    Creates a fresh *Delete Target Customer* order, registers a ``window.confirm``
    dialog handler before clicking the second (delete) icon button on that row,
    and asserts the customer name is no longer visible in the orders table.

    Args:
        owner_page: Authenticated Playwright page for the owner.
        ensure_owner_profile: Session fixture ensuring at least one profile exists.
    """
    order_page, _profile_id, _campaign_id = _navigate_to_orders(owner_page)
    order_page.create_order_first_product("Delete Target Customer", 1)
    assert order_page.has_order("Delete Target Customer"), (
        "'Delete Target Customer' must appear before attempting to delete it"
    )

    # Register dialog handler BEFORE clicking; window.confirm fires synchronously.
    owner_page.once("dialog", lambda dlg: dlg.accept())
    row = owner_page.get_by_role("row").filter(has_text="Delete Target Customer")
    row.get_by_role("button").nth(1).click()

    cell = owner_page.get_by_role("cell", name="Delete Target Customer")
    expect(cell.first).to_be_hidden(timeout=10_000)
    assert not order_page.has_order("Delete Target Customer"), (
        "'Delete Target Customer' must not appear in the orders table after deletion"
    )
