"""Order page object — order list and manual order creation for a campaign."""

import urllib.parse

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class OrderPage(BasePage):
    """Page object for ``/scouts/{profileId}/campaigns/{campaignId}/orders``.

    The HTMX orders page lists orders in a ``<table>`` and exposes a *New
    Order* ``<a>`` link to the order editor (``order_editor.html``).  The editor
    has native form fields (``input#customerName``, ``input#customerPhone``,
    a line-items table, and a *Create Order* submit button) and posts to
    ``/api/orders`` via HTMX.

    Selector notes:

    * The *New Order* action is an ``<a role="button">``-style link; use the
      accessible name "New Order".
    * Customer names appear in ``<td>`` cells in the orders ``<tbody>``.
    * Line-item rows live in ``tbody#line-items-container``; the first row is
      pre-rendered.  *Add Product* is a ``<button>`` calling ``addLineItemRow``.
    * Product selection is a native ``<select>`` with one option
      ("Popping Corn (Bag)") in the local template; the first option is picked.
    * Quantity inputs are ``input[type="number"][name^="items["]``.
    """

    _ORDERS_SUFFIX: str = "/orders"
    _CAMPAIGNS_ROOT: str = "/scouts"

    _NEW_ORDER_BTN: str = "New Order"
    _CREATE_ORDER_BTN: str = "Create Order"
    _UPDATE_ORDER_BTN: str = "Update Order"

    _CUSTOMER_NAME_SEL: str = "input#customerName"
    _CUSTOMER_PHONE_SEL: str = "input#customerPhone"
    _ADD_PRODUCT_BTN: str = "Add Product"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    def goto(self, profile_id: str, campaign_id: str) -> None:
        """Navigate to the orders tab for *campaign_id* under *profile_id*."""
        enc_profile = urllib.parse.quote(profile_id, safe="")
        enc_campaign = urllib.parse.quote(campaign_id, safe="")
        path = f"{self._CAMPAIGNS_ROOT}/{enc_profile}/campaigns/{enc_campaign}{self._ORDERS_SUFFIX}"
        self.navigate(path)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _new_order_button(self) -> Locator:
        """Return locator for the *New Order* link/button in the page header."""
        return self.page.get_by_role("link", name=self._NEW_ORDER_BTN).or_(
            self.page.get_by_role("button", name=self._NEW_ORDER_BTN)
        )

    def _customer_name_input(self) -> Locator:
        """Return locator for the Customer Name text field in the order form."""
        return self.page.locator(self._CUSTOMER_NAME_SEL)

    def _customer_phone_input(self) -> Locator:
        """Return locator for the Phone Number text field in the order form."""
        return self.page.locator(self._CUSTOMER_PHONE_SEL)

    def _create_order_button(self) -> Locator:
        """Return locator for the *Create Order* submit button."""
        return self.page.get_by_role("button", name=self._CREATE_ORDER_BTN)

    def _update_order_button(self) -> Locator:
        """Return locator for the *Update Order* submit button (edit mode)."""
        return self.page.get_by_role("button", name=self._UPDATE_ORDER_BTN)

    def _add_product_button(self) -> Locator:
        """Return locator for the *Add Product* button in the line items table."""
        return self.page.get_by_role("button", name=self._ADD_PRODUCT_BTN)

    def _line_item_rows(self) -> Locator:
        """Return locator for all line-item rows in the editor table body."""
        return self.page.locator("tbody#line-items-container tr.line-item-row")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def create_order_first_product(self, customer_name: str, qty: int = 2) -> None:
        """Click *New Order*, pick the first available product, and submit.

        The local order editor pre-renders one line-item row with a single
        product option ("Popping Corn (Bag)").  This method fills the customer
        fields, sets the quantity on the first row, and submits.

        Args:
            customer_name: Customer full name to enter in the form.
            qty: Quantity for the single line item. Defaults to 2.
        """
        self._new_order_button().first.click()
        self._customer_name_input().wait_for(state="visible", timeout=10_000)
        self._customer_name_input().fill(customer_name)
        self._customer_phone_input().fill("5551234567")
        # Set the quantity on the first (pre-rendered) line-item row.
        first_row = self._line_item_rows().first
        first_row.locator("input.item-qty").fill(str(qty))
        self._create_order_button().click()
        # The save handler returns an HX-Redirect to the orders list.
        self.page.wait_for_url("**/orders", timeout=15_000)
        self.wait_for_loading()

    def create_order(self, customer_name: str, items: list[dict[str, str | int]]) -> None:
        """Click *New Order*, fill the form, and submit.

        Args:
            customer_name: Customer full name to enter in the form.
            items: Line items.  Each dict may have ``"product_name"`` and
                ``"quantity"``; only the quantity is applied to the local
                editor's single pre-rendered row (product selection is fixed).
        """
        self._new_order_button().first.click()
        self._customer_name_input().wait_for(state="visible", timeout=10_000)
        self._fill_order_form(customer_name, items)

    def _fill_order_form(self, customer_name: str, items: list[dict[str, str | int]]) -> None:
        """Fill the *Create Order* form and submit it."""
        self._customer_name_input().fill(customer_name)
        self._fill_line_items(items)
        self._create_order_button().click()
        self.page.wait_for_url("**/orders", timeout=15_000)
        self.wait_for_loading()

    def _fill_line_items(self, items: list[dict[str, str | int]]) -> None:
        """Fill every line item row in the order editor."""
        for index, item in enumerate(items):
            self._ensure_row_exists(index)
            self._fill_row(index, str(item.get("product_name", "")), str(item.get("quantity", 1)))

    def _ensure_row_exists(self, index: int) -> None:
        """Click *Add Product* if the row at *index* does not yet exist."""
        rows = self._line_item_rows().all()
        if index >= len(rows):
            self._add_product_button().click()

    def _fill_row(self, index: int, product_name: str, quantity: str) -> None:
        """Select a product and set the quantity for line-item row *index*.

        The local editor has a single fixed product option, so product_name is
        accepted but only the quantity is applied.
        """
        row = self._line_item_rows().nth(index)
        select = row.locator("select")
        if product_name:
            try:
                select.select_option(label=product_name)
            except Exception:  # noqa: BLE001 — fall back to first option
                select.select_option(index=0)
        else:
            select.select_option(index=0)
        row.locator("input.item-qty").fill(quantity)

    def update_order(self, customer_name: str) -> None:
        """Update the customer name on the edit form and submit (edit mode)."""
        self._customer_name_input().fill(customer_name)
        self._update_order_button().click()
        self.page.wait_for_url("**/orders", timeout=15_000)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def has_order(self, customer_name: str) -> bool:
        """Return ``True`` when *customer_name* appears in the orders table."""
        cell = self.page.get_by_role("cell", name=customer_name)
        try:
            expect(cell.first).to_be_visible(timeout=10_000)
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_order_total(self) -> str:
        """Return the order-total text shown in the editor.

        The order editor renders ``Total: <span id="grand-total-display">``.

        Returns:
            Raw inner text of the total element (e.g. ``"Total: $30.00"``),
            or ``""`` when the element is not visible.
        """
        total = self.page.locator("#grand-total-display")
        if total.first.is_visible():
            return f"Total: {total.first.inner_text()}"
        return ""
