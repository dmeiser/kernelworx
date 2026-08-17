"""Payment page object — payment method selection and storage (UI only)."""

import pathlib

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
    _DELETE_DIALOG_TITLE: str = "Delete Payment Method"
    _DELETE_BTN: str = "Delete"

    # Edit / QR code action labels (verified from PaymentMethodCard.tsx)
    _EDIT_BTN_TEMPLATE: str = "Edit {name}"
    _UPLOAD_QR_BTN_TEMPLATE: str = "Upload QR code for {name}"
    _DELETE_QR_BTN_TEMPLATE: str = "Delete QR code for {name}"
    _VIEW_QR_BTN_TEMPLATE: str = "View QR code for {name}"

    # Edit dialog
    _EDIT_DIALOG_TITLE: str = "Edit Payment Method"
    _EDIT_DIALOG_SUBMIT_BTN: str = "Update"

    # QR upload dialog
    _UPLOAD_QR_DIALOG_TITLE_TEMPLATE: str = "Upload QR Code for {name}"
    _UPLOAD_QR_FILE_INPUT_LABEL: str = "Select QR code image"
    _UPLOAD_QR_UPLOAD_BTN: str = "Upload"
    _QR_PREVIEW_ALT: str = "QR code preview"
    _QR_VIEW_ALT_TEMPLATE: str = "QR code for {name}"

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

    def _delete_button(self, method_type: str) -> Locator:
        """Return the delete button for the card matching *method_type*.

        The button is an IconButton whose accessible name is
        ``"Delete {method_type}"``.

        Args:
            method_type: Exact payment method name (case-sensitive).
        """
        return self._card_for(method_type).get_by_role("button", name=f"Delete {method_type}", exact=True)

    def _delete_dialog_confirm_button(self) -> Locator:
        """Return locator for the *Delete* button in the confirmation dialog."""
        return self.page.get_by_role("dialog").get_by_role("button", name=self._DELETE_BTN)

    def _card_for(self, method_type: str) -> Locator:
        """Return a locator for the payment method card matching *method_type*.

        ``PaymentMethodCard`` renders the method name as a heading-level
        ``<span>``; we filter by its exact text content so renamed methods
        whose new names contain the old name do not collide.

        Args:
            method_type: Exact payment method name (case-sensitive).
        """
        return self.page.locator("div.MuiCard-root").filter(
            has=self.page.get_by_text(method_type, exact=True)
        )

    def _edit_button(self, method_type: str) -> Locator:
        """Return the *Edit* button for the card matching *method_type*."""
        return self._card_for(method_type).get_by_role(
            "button", name=self._EDIT_BTN_TEMPLATE.format(name=method_type), exact=True
        )

    def _upload_qr_button(self, method_type: str) -> Locator:
        """Return the *Upload QR* button for the card matching *method_type*."""
        return self._card_for(method_type).get_by_role(
            "button", name=self._UPLOAD_QR_BTN_TEMPLATE.format(name=method_type), exact=True
        )

    def _delete_qr_button(self, method_type: str) -> Locator:
        """Return the *Delete QR* button for the card matching *method_type*."""
        return self._card_for(method_type).get_by_role(
            "button", name=self._DELETE_QR_BTN_TEMPLATE.format(name=method_type), exact=True
        )

    def _view_qr_button(self, method_type: str) -> Locator:
        """Return the *View QR* button for the card matching *method_type*."""
        return self._card_for(method_type).get_by_role(
            "button", name=self._VIEW_QR_BTN_TEMPLATE.format(name=method_type), exact=True
        )

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

    def delete_payment_method(self, method_type: str) -> None:
        """Click the delete action on the card and confirm the dialog.

        Waits for the confirmation dialog to close and the list to reload
        before returning.

        Args:
            method_type: Name of the custom payment method to delete.
        """
        self._delete_button(method_type).click()
        dialog = self.wait_for_dialog(self._DELETE_DIALOG_TITLE)
        self._delete_dialog_confirm_button().click()
        expect(dialog).to_be_hidden(timeout=10_000)
        self.wait_for_loading()

    def rename_payment_method(self, old_name: str, new_name: str) -> None:
        """Rename a custom payment method through the *Edit Payment Method* dialog.

        Waits for the dialog to close and the list to refetch before returning.

        Args:
            old_name: Current exact name of the custom payment method.
            new_name: Desired new name for the payment method.
        """
        self._edit_button(old_name).click()
        dialog = self.wait_for_dialog(self._EDIT_DIALOG_TITLE)
        self.page.get_by_label(self._DIALOG_FIELD_LABEL).fill(new_name)
        dialog.get_by_role("button", name=self._EDIT_DIALOG_SUBMIT_BTN, exact=True).click()
        expect(dialog).to_be_hidden(timeout=10_000)
        self.wait_for_loading()
        # Wait for the refetched list to reflect the rename.
        expect(self._card_for(new_name).first).to_be_visible(timeout=10_000)
        expect(self._card_for(old_name).first).to_be_hidden(timeout=10_000)

    def upload_qr_code(self, method_type: str, file_path: str | pathlib.Path) -> None:
        """Upload a QR code image for the payment method matching *method_type*.

        Opens the upload dialog, selects *file_path*, waits for the preview to
        render, and submits the upload.

        Args:
            method_type: Exact name of the custom payment method.
            file_path: Path to a PNG/JPG/WEBP image file.
        """
        self._upload_qr_button(method_type).click()
        dialog = self.wait_for_dialog(
            self._UPLOAD_QR_DIALOG_TITLE_TEMPLATE.format(name=method_type)
        )
        file_input = dialog.get_by_label(self._UPLOAD_QR_FILE_INPUT_LABEL)
        file_input.set_input_files(file_path)
        preview = dialog.get_by_alt_text(self._QR_PREVIEW_ALT)
        expect(preview).to_be_visible(timeout=10_000)
        dialog.get_by_role("button", name=self._UPLOAD_QR_UPLOAD_BTN, exact=True).click()
        expect(dialog).to_be_hidden(timeout=20_000)
        self.wait_for_loading()

    def delete_qr_code(self, method_type: str) -> None:
        """Delete the QR code associated with *method_type*.

        The front-end performs the deletion immediately (no confirmation dialog),
        so this helper waits for the list to refetch before returning.

        Args:
            method_type: Exact name of the custom payment method.
        """
        self._delete_qr_button(method_type).click()
        self.wait_for_loading()

    def view_qr_code(self, method_type: str) -> Locator:
        """Open the QR code preview dialog for *method_type*.

        Returns the dialog locator after verifying the rendered QR image is
        visible.  The caller is responsible for closing the dialog.

        Args:
            method_type: Exact name of the payment method.

        Returns:
            Locator for the open QR preview dialog.
        """
        self._view_qr_button(method_type).click()
        dialog = self.wait_for_dialog(f"QR Code for {method_type}")
        image = dialog.get_by_alt_text(
            self._QR_VIEW_ALT_TEMPLATE.format(name=method_type)
        )
        expect(image).to_be_visible(timeout=10_000)
        return dialog

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

    def has_qr_code(self, method_type: str) -> bool:
        """Return ``True`` when the card for *method_type* shows a QR code.

        A visible *View QR* button indicates the payment method has an
        uploaded QR code. The list refetches after upload, so we wait briefly.

        Args:
            method_type: Exact payment method name.
        """
        try:
            expect(self._view_qr_button(method_type).first).to_be_visible(timeout=10_000)
            return True
        except Exception:  # noqa: BLE001
            return False
