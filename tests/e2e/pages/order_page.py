"""Order page object — order list and manual order creation for a campaign."""

import urllib.parse

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class OrderPage(BasePage):
    """Page object for ``/scouts/{profileId}/campaigns/{campaignId}/orders``.

    Shows a table of orders and exposes a *New Order* button that navigates
    to :class:`OrderEditorPage`.  Order creation is performed in the editor
    and then the browser returns to this list.

    Selector notes:

    * Customer names appear in ``<TableCell>`` elements in the orders table.
    * The *New Order* button uses visible text (MUI Button).
    * The ``OrderEditorPage`` heading is ``<Typography variant="h4">`` with
      the text ``"Create Order"``; :meth:`create_order` navigates there,
      fills the form, and submits.

    TODO: add ``data-testid`` attributes to the order table and form fields
    once the smoke-test suite is validated against the running app.
    """

    _ORDERS_SUFFIX: str = "/orders"
    _CAMPAIGNS_ROOT: str = "/scouts"

    # Button / heading text (from component source)
    _NEW_ORDER_BTN: str = "New Order"
    _CREATE_ORDER_BTN: str = "Create Order"

    # Form field labels (OrderEditorPage / CustomerInfoForm)
    _CUSTOMER_NAME_LABEL: str = "Customer Name"
    _ADD_PRODUCT_BTN: str = "Add Product"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance.

        Args:
            page: Active Playwright :class:`~playwright.sync_api.Page`.
        """
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, profile_id: str, campaign_id: str) -> None:
        """Navigate to the orders tab for *campaign_id* under *profile_id*.

        Both IDs are URL-encoded to handle ``PROFILE#uuid`` / ``CAMPAIGN#uuid``
        DynamoDB key patterns.

        Args:
            profile_id: Raw profile identifier string.
            campaign_id: Raw campaign identifier string.
        """
        enc_profile = urllib.parse.quote(profile_id, safe="")
        enc_campaign = urllib.parse.quote(campaign_id, safe="")
        path = f"{self._CAMPAIGNS_ROOT}/{enc_profile}/campaigns/{enc_campaign}{self._ORDERS_SUFFIX}"
        self.navigate(path)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _new_order_button(self) -> Locator:
        """Return locator for the *New Order* button in the page header."""
        return self.get_by_role_button(self._NEW_ORDER_BTN)

    def _customer_name_input(self) -> Locator:
        """Return locator for the *Customer Name* text field in the order form."""
        return self.page.get_by_label(self._CUSTOMER_NAME_LABEL)

    def _create_order_button(self) -> Locator:
        """Return locator for the *Create Order* submit button."""
        return self.get_by_role_button(self._CREATE_ORDER_BTN)

    def _add_product_button(self) -> Locator:
        """Return locator for the *Add Product* button in the line items table."""
        return self.get_by_role_button(self._ADD_PRODUCT_BTN)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def create_order_first_product(self, customer_name: str, qty: int = 2) -> None:
        """Click *New Order*, pick the first available product, and submit.

        Encapsulates the full creation flow so test helpers do not need access
        to private locator methods.  Waits for the loading indicator to clear
        before returning.

        Args:
            customer_name: Customer full name to enter in the form.
            qty: Quantity for the single line item. Defaults to 2.
        """
        self._new_order_button().click()
        self.wait_for_loading()
        self._customer_name_input().fill(customer_name)
        self._add_product_button().click()
        product_row = self.page.get_by_role("row").nth(1)  # nth(0) is <thead>
        product_row.get_by_role("combobox").click()
        self.page.get_by_role("option").first.click()
        product_row.locator('input[type="number"]').fill(str(qty))
        self._create_order_button().click()
        # Wait for navigation from /orders/new back to the orders list.
        self.page.wait_for_url("**/orders", timeout=15_000)
        self.wait_for_loading()

    def create_order(self, customer_name: str, items: list[dict[str, str | int]]) -> None:
        """Click *New Order*, fill the form, and submit.

        Waits for the page to navigate back to the orders list after a
        successful submission.

        Args:
            customer_name: Customer full name to enter in the form.
            items: Line items to add.  Each dict must have:

                * ``"product_name"`` – visible text of the product option.
                * ``"quantity"`` – integer or string quantity.

        Example::

            order_page.create_order(
                "Jane Smith",
                [{"product_name": "Trail's End Popcorn", "quantity": 2}],
            )
        """
        self._new_order_button().click()
        self.wait_for_loading()
        self._fill_order_form(customer_name, items)

    def _fill_order_form(self, customer_name: str, items: list[dict[str, str | int]]) -> None:
        """Fill the *Create Order* form and submit it.

        Separated from :meth:`create_order` to stay within the complexity budget.

        Args:
            customer_name: Customer name string.
            items: List of line-item dicts (see :meth:`create_order`).
        """
        self._customer_name_input().fill(customer_name)
        self._fill_line_items(items)
        self._create_order_button().click()
        self.wait_for_loading()

    def _fill_line_items(self, items: list[dict[str, str | int]]) -> None:
        """Fill every line item row in the order editor.

        Adds extra rows as needed using the *Add Product* button.

        Args:
            items: Ordered list of ``{"product_name": ..., "quantity": ...}`` dicts.
        """
        for index, item in enumerate(items):
            self._ensure_row_exists(index)
            self._fill_row(index, str(item["product_name"]), str(item["quantity"]))

    def _ensure_row_exists(self, index: int) -> None:
        """Click *Add Product* if the row at *index* does not yet exist.

        Args:
            index: Zero-based row index.
        """
        rows = self.page.get_by_role("row").all()
        # rows[0] is the <thead> row; body rows start at rows[1]
        if index >= len(rows) - 1:
            self._add_product_button().click()

    def _fill_row(self, index: int, product_name: str, quantity: str) -> None:
        """Select a product and set the quantity for line-item row *index*.

        The row index is 1-based in the DOM table (skipping the header row).
        Uses the Select combobox in the row for product selection.

        Args:
            index: Zero-based row index in the line items.
            product_name: Visible option text in the product Select.
            quantity: Quantity as a string.
        """
        row = self.page.get_by_role("row").nth(index + 1)  # +1 to skip thead
        # Product Select inside the row – there is one combobox per line item
        row.get_by_role("combobox").click()
        self.page.get_by_role("option", name=product_name).click()
        # Quantity text field (type="number") inside the same row
        row.locator('input[type="number"]').fill(quantity)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def has_order(self, customer_name: str) -> bool:
        """Return ``True`` when *customer_name* appears in the orders table.

        Waits up to 10 seconds for the row to appear so that in-flight
        GraphQL refreshes after order creation have time to complete.

        Args:
            customer_name: Text to search for in any visible table cell.
        """
        cell = self.page.get_by_role("cell", name=customer_name)
        try:
            expect(cell.first).to_be_visible(timeout=10_000)
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_order_total(self) -> str:
        """Return the order-total text shown at the bottom of the line items table.

        The ``OrderEditorPage`` renders a ``Typography variant="h6"`` with
        text ``"Total: $X.XX"`` at the bottom of the products section.

        Returns:
            Raw inner text of the total element (e.g. ``"Total: $12.50"``),
            or ``""`` when the element is not visible.
        """
        # TODO: verify selector – the total is in a Typography h6 scoped inside the products card
        total_locator = self.page.locator("div.MuiCard-root h6", has_text="Total:")
        if total_locator.first.is_visible():
            return total_locator.first.inner_text()
        return ""
