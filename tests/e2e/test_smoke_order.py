"""Smoke tests for order creation and list visibility.

Navigation strategy
-------------------
The simple creation/list tests navigate from:
  Dashboard → first profile → first campaign → orders page.
The full-form lifecycle test seeds its own two-product catalog/campaign so it
does not depend on the contents of an arbitrary existing campaign.

The owner account must have at least one campaign when these tests run.
Running ``tests/e2e/test_smoke_campaign.py`` first (which creates
*Smoke Test Campaign 2026*) satisfies this requirement in a freshly seeded env.

Product selection
-----------------
``_submit_order_first_product`` opens the product combobox and selects the
**first** available option, keeping the simple creation tests independent of
catalog contents.  ``test_full_form_order_lifecycle_with_money`` seeds a
dedicated two-product catalog and campaign so it can safely select and modify
multiple line items.

Payment method
--------------
The simple creation tests rely on the editor's default payment method.
``test_full_form_order_lifecycle_with_money`` creates a uniquely named custom
payment method, selects it for the order, verifies it persists on the edit
page, and deletes it in a ``finally`` block.

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
from tests.e2e.pages.catalogs_page import CatalogsPage
from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.order_page import OrderPage
from tests.e2e.pages.payment_page import PaymentPage
from tests.e2e.utils.money import assert_currency, parse_currency

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


def _navigate_to_orders(owner_page: Page, profile_name: str) -> tuple[OrderPage, str, str]:
    """Navigate from dashboard to the owned profile's first campaign orders page.

    Steps:
    1. Dashboard → click the owned seller profile (from ``ensure_owner_profile``).
    2. Campaigns list → click first campaign (seeding one if none exist).
    3. Extract profile_id / campaign_id from URL.
    4. Navigate directly to orders sub-page and return :class:`OrderPage`.

    Args:
        owner_page: Authenticated Playwright page for the owner.
        profile_name: Owned seller profile name (from ``ensure_owner_profile``).

    Returns:
        3-tuple ``(order_page, profile_id, campaign_id)`` where *order_page* is
        focused on the orders for the navigated campaign.
    """
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    dashboard.click_profile(profile_name)

    campaign_page = CampaignPage(owner_page)
    campaign_page.wait_for_loading()
    campaigns = campaign_page.get_campaign_names()
    if not campaigns:
        # No campaigns on the owned profile; seed one for orders smoke tests.
        profile_match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
        assert profile_match, f"Expected /scouts/{{id}}/campaigns URL, got: {owner_page.url}"
        seed_profile_id = urllib.parse.unquote(profile_match.group(1))
        seed_name = f"Order Seed Campaign {int(time.time())}"
        campaign_page.create_campaign_first_catalog(seed_name, seed_profile_id)
        # Poll with fresh navigations; campaign visibility can lag briefly.
        for _ in range(12):  # up to ~60s
            campaign_page.goto(seed_profile_id)
            campaigns = campaign_page.get_campaign_names()
            if campaigns:
                break
            owner_page.wait_for_timeout(5_000)
        assert campaigns, "Failed to seed campaign for order smoke tests"

    campaign_page.click_campaign(campaigns[0])

    profile_id, campaign_id = _extract_profile_and_campaign_ids(owner_page.url)
    order_page = OrderPage(owner_page)
    order_page.goto(profile_id, campaign_id)
    return order_page, profile_id, campaign_id


def _create_two_product_campaign(owner_page: Page, profile_name: str) -> tuple[OrderPage, str, str]:
    """Seed a dedicated two-product catalog and campaign for the owned profile.

    Creates a fresh catalog with two priced products, opens the catalog preview,
    creates a campaign from that catalog, and navigates to the campaign's orders
    page.  This guarantees the full-form order test has at least two distinct
    product options to select and modify.

    Args:
        owner_page: Authenticated Playwright page for the owner.
        profile_name: Owned seller profile name (from ``ensure_owner_profile``).

    Returns:
        3-tuple ``(order_page, profile_id, campaign_id)`` focused on the seeded
        campaign's orders page.
    """
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_profiles_loaded()
    dashboard.click_profile(profile_name)

    profile_match = re.search(r"/scouts/([^/]+)/campaigns", owner_page.url)
    assert profile_match, f"Expected /scouts/{{id}}/campaigns URL, got: {owner_page.url}"
    profile_id = urllib.parse.unquote(profile_match.group(1))

    catalog_name = f"Two Product Catalog {uuid4().hex[:8]}"
    products = [
        {"productName": "Caramel Popcorn", "price": 10.0},
        {"productName": "Cheese Popcorn", "price": 15.0},
    ]
    catalogs = CatalogsPage(owner_page)
    catalogs.goto()
    catalogs.switch_to_my_catalogs()
    catalogs.create_catalog(catalog_name, products)
    catalogs.view_catalog(catalog_name)

    owner_page.get_by_role("button", name="Create Campaign", exact=True).first.click()
    owner_page.wait_for_url("**/create-campaign**", timeout=10_000)
    OrderPage(owner_page).wait_for_loading()

    # Ensure the intended profile is selected (dropdown uses PROFILE#id values).
    profile_combobox = owner_page.get_by_role("combobox", name="Select Profile")
    if profile_combobox.is_visible():
        profile_combobox.click()
        listbox = owner_page.get_by_role("listbox")
        expect(listbox).to_be_visible(timeout=5_000)
        candidate_ids = {profile_id}
        if not profile_id.startswith("PROFILE#"):
            candidate_ids.add(f"PROFILE#{profile_id}")
        option = listbox.locator('[role="option"]:not([aria-disabled="true"])').first
        for candidate in candidate_ids:
            candidate_option = listbox.locator(f'[role="option"][data-value="{candidate}"]')
            if candidate_option.count() > 0:
                option = candidate_option
                break
        expect(option).to_be_visible(timeout=5_000)
        option.click()
        expect(listbox).to_be_hidden(timeout=5_000)

    campaign_name = f"Two Product Campaign {uuid4().hex[:8]}"
    owner_page.get_by_label("Campaign Name").fill(campaign_name)
    owner_page.get_by_role("button", name="Create Campaign", exact=True).click()
    owner_page.wait_for_url("**/campaigns/**", timeout=15_000)
    OrderPage(owner_page).wait_for_loading()

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
def test_create_order(
    owner_page: Page,
    _module_state: dict[str, str],
    ensure_owner_profile: str,
    ensure_owner_catalog: None,
) -> None:
    """Create an order for Jane Smith with 2 units of the first available product.

    Verifies that after submitting the order editor the app returns to the
    orders list and *Jane Smith* is visible as a table entry — confirming the
    order was persisted and the UI reflects it.

    Stores ``profile_id``, ``campaign_id``, and ``customer_name`` in
    ``_module_state`` for use by ``test_order_appears_in_list``.
    """
    order_page, profile_id, campaign_id = _navigate_to_orders(owner_page, ensure_owner_profile)
    _submit_order_first_product(order_page, _CUSTOMER_NAME, _ORDER_QTY)
    assert order_page.has_order(_CUSTOMER_NAME), f"'{_CUSTOMER_NAME}' must appear in the orders table after creation"
    _module_state["profile_id"] = profile_id
    _module_state["campaign_id"] = campaign_id
    _module_state["customer_name"] = _CUSTOMER_NAME


@pytest.mark.smoke
@pytest.mark.slow
def test_full_form_order_lifecycle_with_money(
    owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None
) -> None:
    """Create a full order with a custom payment method and verify money math end-to-end.

    Seeds a dedicated two-product catalog/campaign so the test is not coupled to
    an arbitrary existing campaign.  It creates a uniquely named custom payment
    method, selects it for the order, asserts per-row subtotals and the editor
    total, changes a quantity and verifies the subtotal/total update, submits,
    checks the orders-list total, confirms the payment method persists on the
    edit page, and verifies the campaign summary *Total Sales* tile.
    """
    payment_method_name = f"Custom Pay {uuid4().hex[:8]}"
    payment_page = PaymentPage(owner_page)
    payment_page.goto()

    try:
        payment_page.add_payment_method(payment_method_name)

        order_page, profile_id, campaign_id = _create_two_product_campaign(owner_page, ensure_owner_profile)

        # Capture baseline Total Sales so the assertion is isolated from prior orders.
        baseline_text = order_page.get_summary_total_sales()
        baseline_cents = int(parse_currency(baseline_text or "$0.00") * 100)

        customer_name = f"Full Form Customer {uuid4().hex[:8]}"
        phone = "5559876543"
        address = {
            "street": "123 Kernel Lane",
            "city": "Austin",
            "state": "TX",
            "zip": "78701",
        }
        notes = "Deliver to front porch. Leave behind the planter."

        order_page._new_order_button().click()
        order_page.wait_for_loading()

        order_page.fill_full_order_form(
            customer_name=customer_name,
            phone=phone,
            items=[
                {"product_name": "Caramel Popcorn", "quantity": 2},
                {"product_name": "Cheese Popcorn", "quantity": 3},
            ],
            address=address,
            payment_method=payment_method_name,
            notes=notes,
        )

        # Read displayed prices and assert initial subtotals/total match quantity * price.
        price_0_text = order_page.get_line_item_price(0)
        price_1_text = order_page.get_line_item_price(1)
        price_0_cents = int(parse_currency(price_0_text) * 100)
        price_1_cents = int(parse_currency(price_1_text) * 100)

        assert_currency(order_page.get_line_item_subtotal(0), price_0_cents * 2)
        assert_currency(order_page.get_line_item_subtotal(1), price_1_cents * 3)

        initial_total_cents = price_0_cents * 2 + price_1_cents * 3
        assert_currency(order_page.get_editor_total(), initial_total_cents)

        # Change an existing quantity and verify the subtotal/total update.
        order_page._set_line_item_quantity(1, "1")
        updated_subtotal_1_cents = price_1_cents * 1
        assert_currency(order_page.get_line_item_subtotal(1), updated_subtotal_1_cents)
        updated_total_cents = price_0_cents * 2 + updated_subtotal_1_cents
        assert_currency(order_page.get_editor_total(), updated_total_cents)

        # Submit and verify the orders list shows the expected total.
        order_page._create_order_button().click()
        owner_page.wait_for_url("**/orders", timeout=15_000)
        order_page.wait_for_loading()

        expect(owner_page.get_by_role("cell", name=customer_name).first).to_be_visible(timeout=10_000)
        list_total_text = order_page.get_list_total_for_customer(customer_name)
        assert_currency(list_total_text, updated_total_cents)

        # Verify the custom payment method persisted by opening the edit page.
        order_page.click_edit_order(customer_name)
        expect(owner_page.get_by_role("heading", name="Edit Order")).to_be_visible(timeout=10_000)
        persisted_payment = order_page.get_selected_payment_method()
        assert persisted_payment == payment_method_name, (
            f"Expected payment method '{payment_method_name}' to persist; got '{persisted_payment}'"
        )

        # Return to the orders page and verify the campaign summary reflects the order.
        order_page.goto(profile_id, campaign_id)
        summary_total_text = order_page.get_summary_total_sales()
        assert_currency(summary_total_text, baseline_cents + updated_total_cents)
    finally:
        payment_page.goto()
        if payment_page.has_payment_method(payment_method_name):
            payment_page.delete_payment_method(payment_method_name)


@pytest.mark.smoke
@pytest.mark.slow
def test_create_order_without_phone(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Create an order with a blank phone number and verify it is accepted."""
    order_page, _profile_id, _campaign_id = _navigate_to_orders(owner_page, ensure_owner_profile)
    customer_name = "No Phone Customer"
    order_page.create_order_first_product(customer_name, 1, phone=None)
    assert order_page.has_order(customer_name), (
        f"'{customer_name}' must appear in the orders table when no phone is provided"
    )


@pytest.mark.smoke
@pytest.mark.slow
def test_invalid_phone_preserves_form(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Submit with an invalid phone and verify the error appears without losing data."""
    order_page, _profile_id, _campaign_id = _navigate_to_orders(owner_page, ensure_owner_profile)
    customer_name = "Bad Phone Customer"
    order_page.submit_order_with_invalid_phone(customer_name, "123-invalid")

    assert "Phone number must be a valid 10-digit US number" in order_page.get_visible_alert_text()
    expect(owner_page.get_by_label("Customer Name")).to_have_value(customer_name)
    expect(owner_page).to_have_url(re.compile(r"/orders/new$"), timeout=10_000)


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
def test_edit_order(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Create an order, edit it via the edit button, and verify the updated name.

    Creates a fresh *Edit Target Customer* order, clicks the first (edit) icon
    button on that row, changes the customer name to *Edited Customer*, submits
    with the *Update Order* button, and asserts the new name appears in the
    orders list.

    Args:
        owner_page: Authenticated Playwright page for the owner.
        ensure_owner_profile: Session fixture ensuring at least one profile exists.
    """
    order_page, _profile_id, _campaign_id = _navigate_to_orders(owner_page, ensure_owner_profile)
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

    assert order_page.has_order("Edited Customer"), "'Edited Customer' must appear in the orders table after editing"


@pytest.mark.smoke
@pytest.mark.slow
def test_delete_order(owner_page: Page, ensure_owner_profile: str, ensure_owner_catalog: None) -> None:
    """Create an order, delete it via the delete button, and verify it disappears.

    Creates a fresh *Delete Target Customer* order, registers a ``window.confirm``
    dialog handler before clicking the second (delete) icon button on that row,
    and asserts the customer name is no longer visible in the orders table.

    Args:
        owner_page: Authenticated Playwright page for the owner.
        ensure_owner_profile: Session fixture ensuring at least one profile exists.
    """
    order_page, _profile_id, _campaign_id = _navigate_to_orders(owner_page, ensure_owner_profile)
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
