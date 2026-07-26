"""Payment page object — payment method selection and storage (UI only).

Covers the HTMX ``/payment-methods`` route (``payment_methods.html``).

Note: the local test server renders the built-in payment methods returned by
``render_payment_methods_handler`` (Cash and Venmo by default) but does NOT
wire the *Add Payment Method* create dialog or the delete endpoints — those
HTMX triggers hit unimplemented routes.  The add/delete helper methods are
retained for API compatibility; tests that exercise them skip locally.
"""

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class PaymentPage(BasePage):
    """Page object for the ``/payment-methods`` route."""

    PATH: str = "/payment-methods"

    _ADD_BTN: str = "Add Payment Method"
    _DELETE_BTN: str = "Delete"

    # Payment method cards: div.card[id^="pm-card-"]; the method name is the
    # first <span> inside the card.
    _CARD_SEL: str = "div.card[id^='pm-card-']"
    _NAME_SPAN_SEL: str = "div.card[id^='pm-card-'] span"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

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

    def _card_for(self, method_type: str) -> Locator:
        """Return a locator for the payment method card matching *method_type*."""
        return self.page.locator(self._CARD_SEL).filter(has_text=method_type)

    def _delete_button(self, method_type: str) -> Locator:
        """Return the delete button for the card matching *method_type*.

        The card's delete icon button has ``aria-label="Delete {method_type}"``.
        """
        return self._card_for(method_type).get_by_role("button", name=f"Delete {method_type}", exact=True)

    # ------------------------------------------------------------------
    # Actions (retained for API compatibility; not wired in the local server)
    # ------------------------------------------------------------------

    def add_payment_method(self, method_type: str) -> None:
        """Click *Add Payment Method*, fill the dialog, and confirm."""
        self._add_button().click()
        # The create dialog is not implemented in the local server; this method
        # exists for API compatibility.  Callers should skip tests that use it.
        expect(self.page.get_by_role("dialog")).to_be_visible(timeout=5_000)

    def delete_payment_method(self, method_type: str) -> None:
        """Click the delete action on the card and confirm the dialog."""
        self._delete_button(method_type).click()
        expect(self.page.get_by_role("dialog")).to_be_visible(timeout=5_000)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def has_payment_method(self, method_type: str) -> bool:
        """Return ``True`` when a card with *method_type* is visible."""
        card = self._card_for(method_type)
        try:
            return bool(card.first.is_visible())
        except Exception:  # noqa: BLE001
            return False

    def get_payment_method_names(self) -> list[str]:
        """Return the inner text of every visible payment method card name span."""
        return self.page.locator(self._NAME_SPAN_SEL).all_inner_texts()
