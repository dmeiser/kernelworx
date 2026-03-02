"""Payment page object — payment method selection and storage (UI only)."""

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class PaymentPage(BasePage):
    """Page object for the ``/payment-methods`` route.

    Manages custom payment methods (e.g. Venmo, Zelle).  Cash and Check are
    always available and rendered as read-only *built-in* cards.

    Selector notes:

    * Payment method names are rendered as ``<span>`` elements styled with
      ``MUI Typography variant="h6"`` inside each ``PaymentMethodCard``.
    * The *Add Payment Method* button is a plain MUI Button (no ``data-testid``).
    * The ``CreatePaymentMethodDialog`` has a TextField with
      ``label="Payment Method Name"`` and a *Create* submit button.

    TODO: add ``data-testid="payment-method-card"`` to ``PaymentMethodCard``
    for more robust targeting.
    """

    PATH: str = "/payment-methods"

    # Button / label text (verified from component source)
    _ADD_BTN: str = "Add Payment Method"
    _DIALOG_FIELD_LABEL: str = "Payment Method Name"
    _DIALOG_SUBMIT_BTN: str = "Create"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance.

        Args:
            page: Active Playwright :class:`~playwright.sync_api.Page`.
        """
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self) -> None:
        """Navigate to ``/payment-methods`` and wait for content to load."""
        self.navigate(self.PATH)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _add_button(self) -> Locator:
        """Return locator for the *Add Payment Method* button."""
        return self.get_by_role_button(self._ADD_BTN)

    def _dialog_name_input(self) -> Locator:
        """Return locator for the *Payment Method Name* field in the dialog."""
        return self.page.get_by_label(self._DIALOG_FIELD_LABEL)

    def _dialog_submit_button(self) -> Locator:
        """Return locator for the *Create* button in the create dialog."""
        # Scoped inside the open dialog to avoid collisions with other buttons
        return self.page.get_by_role("dialog").get_by_role("button", name=self._DIALOG_SUBMIT_BTN)

    def _card_for(self, method_type: str) -> Locator:
        """Return a locator for the payment method card matching *method_type*.

        ``PaymentMethodCard`` renders the method name as a heading-level
        ``<span>``; we filter by its text content.

        Args:
            method_type: Exact payment method name (case-sensitive).
        """
        return self.page.locator("div.MuiCard-root").filter(has_text=method_type)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def add_payment_method(self, method_type: str) -> None:
        """Click *Add Payment Method*, fill the dialog, and confirm.

        Waits for the dialog to close before returning so callers can
        immediately call :meth:`has_payment_method`.

        Args:
            method_type: Name for the new payment method (e.g. ``"Venmo"``).
        """
        self._add_button().click()
        dialog = self.wait_for_dialog("Create Payment Method")
        self._dialog_name_input().fill(method_type)
        self._dialog_submit_button().click()
        expect(dialog).to_be_hidden(timeout=10_000)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def has_payment_method(self, method_type: str) -> bool:
        """Return ``True`` when a card with *method_type* is visible.

        Covers both built-in names (Cash, Check) and custom methods created
        via :meth:`add_payment_method`.

        Args:
            method_type: Payment method name to search for.
        """
        card = self._card_for(method_type)
        return card.first.is_visible()

    def get_payment_method_names(self) -> list[str]:
        """Return the inner text of every visible payment method card heading.

        Returns:
            List of method name strings in DOM order.
        """
        # Each card has exactly one h6 span (the method name)
        spans = self.page.locator("div.MuiCard-root h6")
        return spans.all_inner_texts()
