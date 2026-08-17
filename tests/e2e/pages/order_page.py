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
    _CUSTOMER_PHONE_LABEL: str = "Phone Number"
    _STREET_ADDRESS_LABEL: str = "Street Address"
    _CITY_LABEL: str = "City"
    _STATE_LABEL: str = "State"
    _ZIP_CODE_LABEL: str = "Zip Code"
    _PAYMENT_METHOD_LABEL: str = "Payment Method"
    _NOTES_LABEL: str = "Notes"
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

    def _customer_phone_input(self) -> Locator:
        """Return locator for the *Phone Number* text field in the order form."""
        return self.page.get_by_label(self._CUSTOMER_PHONE_LABEL)

    def _street_address_input(self) -> Locator:
        """Return locator for the *Street Address* text field in the order form."""
        return self.page.get_by_label(self._STREET_ADDRESS_LABEL)

    def _city_input(self) -> Locator:
        """Return locator for the *City* text field in the order form."""
        return self.page.get_by_label(self._CITY_LABEL)

    def _state_input(self) -> Locator:
        """Return locator for the *State* autocomplete in the order form."""
        return self.page.get_by_label(self._STATE_LABEL)

    def _zip_code_input(self) -> Locator:
        """Return locator for the *Zip Code* text field in the order form."""
        return self.page.get_by_label(self._ZIP_CODE_LABEL)

    def _payment_method_select(self) -> Locator:
        """Return locator for the *Payment Method* select in the order form.

        MUI ``Select`` renders a visible combobox without an ``aria-label``;
        the label is associated with a hidden input.  We scope the combobox
        to the FormControl that contains the *Payment Method* label.
        """
        return self.page.locator(
            '.MuiFormControl-root:has(label:has-text("Payment Method")) [role="combobox"]'
        )

    def _notes_input(self) -> Locator:
        """Return locator for the *Notes* multiline field in the order form."""
        return self.page.get_by_label(self._NOTES_LABEL)

    def _create_order_button(self) -> Locator:
        """Return locator for the *Create Order* submit button."""
        return self.get_by_role_button(self._CREATE_ORDER_BTN)

    def _add_product_button(self) -> Locator:
        """Return locator for the *Add Product* button in the line items table."""
        return self.get_by_role_button(self._ADD_PRODUCT_BTN)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def create_order_first_product(
        self,
        customer_name: str,
        qty: int = 2,
        *,
        phone: str | None = "5551234567",
    ) -> None:
        """Click *New Order*, pick the first available product, and submit.

        Encapsulates the full creation flow so test helpers do not need access
        to private locator methods.  Waits for the loading indicator to clear
        before returning.

        Args:
            customer_name: Customer full name to enter in the form.
            qty: Quantity for the single line item. Defaults to 2.
            phone: Phone number to enter, or ``None`` to leave the field blank.
        """
        self._new_order_button().click()
        self.wait_for_loading()
        self._customer_name_input().fill(customer_name)
        if phone is not None:
            self._customer_phone_input().fill(phone)
        self._add_product_button().click()
        product_row = self.page.get_by_role("row").nth(1)  # nth(0) is <thead>
        product_row.get_by_role("combobox").click()
        self.page.get_by_role("option").first.click()
        product_row.locator('input[type="number"]').fill(str(qty))
        self._create_order_button().click()
        # Wait for navigation from /orders/new back to the orders list.
        self.page.wait_for_url("**/orders", timeout=15_000)
        self.wait_for_loading()

    def submit_order_with_invalid_phone(self, customer_name: str, phone: str, qty: int = 2) -> None:
        """Fill the form with an invalid phone and submit without navigating away.

        Args:
            customer_name: Customer full name to enter in the form.
            phone: Invalid phone string to enter.
            qty: Quantity for the single line item. Defaults to 2.
        """
        self._new_order_button().click()
        self.wait_for_loading()
        self._customer_name_input().fill(customer_name)
        self._customer_phone_input().fill(phone)
        self._add_product_button().click()
        product_row = self.page.get_by_role("row").nth(1)
        product_row.get_by_role("combobox").click()
        self.page.get_by_role("option").first.click()
        product_row.locator('input[type="number"]').fill(str(qty))
        self._create_order_button().click()
        # The form should stay on the creation page and show a validation alert.
        expect(self.page.get_by_role("alert")).to_be_visible(timeout=10_000)
        self.page.wait_for_url("**/orders/new", timeout=10_000)

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

    def _fill_row_by_option_index(self, index: int, option_index: int, quantity: str) -> None:
        """Select the *option_index* product and set the quantity for row *index*.

        Useful when the test wants to read the displayed price from the row
        rather than hard-coding a product name.

        Args:
            index: Zero-based row index in the line items.
            option_index: Zero-based index in the opened product dropdown.
            quantity: Quantity as a string.
        """
        row = self.page.get_by_role("row").nth(index + 1)  # +1 to skip thead
        row.get_by_role("combobox").click()
        self.page.get_by_role("option").nth(option_index).click()
        row.locator('input[type="number"]').fill(quantity)

    def _fill_address(self, address: dict[str, str]) -> None:
        """Fill the customer address fields when values are present.

        Args:
            address: Mapping with optional keys ``street``, ``city``,
                ``state``, and ``zip``.
        """
        if street := address.get("street"):
            self._street_address_input().fill(street)
        if city := address.get("city"):
            self._city_input().fill(city)
        if state := address.get("state"):
            self._state_input().fill(state)
        if zip_code := address.get("zip"):
            self._zip_code_input().fill(zip_code)

    def _select_payment_method(self, payment_method: str) -> None:
        """Open the payment method dropdown and select *payment_method*.

        Waits for the option to appear so the helper tolerates the brief
        GraphQL load window for payment methods.

        Args:
            payment_method: Visible option text in the dropdown.
        """
        select = self._payment_method_select()
        expect(select).to_be_visible(timeout=10_000)
        select.click()
        option = self.page.get_by_role("option", name=payment_method)
        expect(option).to_be_visible(timeout=10_000)
        option.click()

    def fill_full_order_form(
        self,
        customer_name: str,
        phone: str | None,
        items: list[dict[str, str | int]],
        address: dict[str, str],
        payment_method: str,
        notes: str,
    ) -> None:
        """Fill the full order editor form without submitting.

        Args:
            customer_name: Customer full name.
            phone: Phone number, or ``None`` to leave blank.
            items: Line items to add (see :meth:`create_order`).
            address: Customer address with optional ``street``, ``city``,
                ``state``, and ``zip`` keys.
            payment_method: Visible payment method option.
            notes: Free-form order notes.
        """
        self._customer_name_input().fill(customer_name)
        if phone is not None:
            self._customer_phone_input().fill(phone)
        self._fill_address(address)
        self._fill_line_items(items)
        self._select_payment_method(payment_method)
        self._notes_input().fill(notes)

    def create_full_order(
        self,
        customer_name: str,
        items: list[dict[str, str | int]],
        address: dict[str, str],
        payment_method: str,
        notes: str,
        *,
        phone: str | None = "5551234567",
    ) -> None:
        """Click *New Order*, fill the full form, and submit.

        Waits for navigation back to the orders list after a successful
        submission.

        Args:
            customer_name: Customer full name.
            items: Line items to add (see :meth:`create_order`).
            address: Customer address with optional ``street``, ``city``,
                ``state``, and ``zip`` keys.
            payment_method: Visible payment method option.
            notes: Free-form order notes.
            phone: Phone number; defaults to a valid 10-digit number. Pass
                ``None`` to leave the field blank.
        """
        self._new_order_button().click()
        self.wait_for_loading()
        self.fill_full_order_form(customer_name, phone, items, address, payment_method, notes)
        self._create_order_button().click()
        self.page.wait_for_url("**/orders", timeout=15_000)
        self.wait_for_loading()

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
        return self.get_editor_total()

    def get_editor_total(self) -> str:
        """Return the editor total text (``Total: $X.XX``) from the products card.

        Returns:
            Raw inner text of the total element, or ``""`` when it is not visible.
        """
        total_locator = self.page.locator("h6", has_text="Total:")
        if total_locator.first.is_visible():
            return total_locator.first.inner_text()
        return ""

    def get_line_item_price(self, index: int) -> str:
        """Return the per-row price cell text for line item *index*.

        Waits for the cell to leave the placeholder ``—`` state so callers can
        read the price after selecting a product.

        Args:
            index: Zero-based row index in the line items.

        Returns:
            Raw price text (e.g. ``"$12.50"``), or ``""`` if the row is missing.
        """
        row = self.page.get_by_role("row").nth(index + 1)  # +1 to skip thead
        price_cell = row.get_by_role("cell").nth(2)
        try:
            expect(price_cell).not_to_have_text("—", timeout=5_000)
        except Exception:  # noqa: BLE001
            return ""
        return price_cell.inner_text()

    def get_line_item_subtotal(self, index: int) -> str:
        """Return the per-row subtotal cell text for line item *index*.

        Args:
            index: Zero-based row index in the line items.

        Returns:
            Raw subtotal text (e.g. ``"$25.00"``), or ``""`` if the row is missing.
        """
        row = self.page.get_by_role("row").nth(index + 1)  # +1 to skip thead
        subtotal_cell = row.get_by_role("cell").nth(3)
        return subtotal_cell.inner_text()

    def get_list_total_for_customer(self, customer_name: str) -> str:
        """Return the *Total* cell text for the row containing *customer_name*.

        The total cell is identified as the right-aligned cell whose text starts
        with ``$``.

        Args:
            customer_name: Customer name used to locate the table row.

        Returns:
            Raw total text (e.g. ``"$25.00"``), or ``""`` when the row is missing.
        """
        row = self.page.get_by_role("row").filter(has_text=customer_name).first
        if not row.is_visible():
            return ""
        for cell in row.get_by_role("cell").all():
            text = cell.inner_text()
            if text.startswith("$"):
                return text
        return ""

    def get_summary_total_sales(self) -> str:
        """Return the *Total Sales* value from the campaign summary tiles.

        Returns:
            Raw currency text (e.g. ``"$25.00"``), or ``""`` when the tile is not visible.
        """
        tile = self.page.locator("div.MuiPaper-root").filter(has_text="Total Sales").first
        if not tile.is_visible():
            return ""
        return tile.locator("h4").first.inner_text()
