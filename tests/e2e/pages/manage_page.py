"""Profile management page object — edit, delete, and transfer ownership.

Covers the HTMX ``/scouts/{profileId}/manage`` page (``scout_management.html``).

The HTMX template implements profile editing and deletion but does NOT render
a *Transfer Ownership* button (there is no shares table in the static
template), so ``transfer_ownership_button_is_visible`` returns ``False``.
Invite/sharing actions on the same URL are handled by :class:`SharePage`.
"""

import urllib.parse

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class ManagePage(BasePage):
    """Page object for /scouts/{profileId}/manage (scout_management.html)."""

    _MANAGE_SUFFIX: str = "/manage"
    _SELLER_NAME_SEL: str = "input#profile-name"
    _SAVE_BTN: str = "Save Changes"
    _DELETE_SCOUT_BTN: str = "Delete Scout"
    _DELETE_PERM_BTN: str = "Delete Permanently"
    _DELETE_DIALOG_TITLE: str = "Delete Seller Profile?"
    _DELETE_DIALOG_SEL: str = "#delete-profile-dialog"
    _TRANSFER_BTN: str = "Transfer Ownership"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    def goto(self, profile_id: str) -> None:
        """Navigate to the management page for *profile_id* (URL-encoded)."""
        encoded = urllib.parse.quote(profile_id, safe="")
        self.navigate(f"/scouts/{encoded}{self._MANAGE_SUFFIX}")
        self.wait_for_loading()

    def _seller_name_input(self) -> Locator:
        """Return locator for the Seller Name text field."""
        return self.page.locator(self._SELLER_NAME_SEL)

    def get_seller_name(self) -> str:
        """Return current value of the Seller Name input."""
        return self._seller_name_input().input_value()

    def transfer_ownership_button_is_visible(self) -> bool:
        """Return True when a Transfer Ownership button is visible and enabled.

        The HTMX scout-management template does not render a shares table, so
        this always returns ``False`` against the local server.  (Retained for
        API compatibility with the original suite.)
        """
        btn = self.page.get_by_role("button", name=self._TRANSFER_BTN, exact=True).first
        try:
            return bool(btn.is_visible() and btn.is_enabled())
        except Exception:  # noqa: BLE001 — button absent
            return False

    def edit_seller_name(self, new_name: str) -> None:
        """Clear the Seller Name field, type *new_name*, and click Save Changes."""
        name_input = self._seller_name_input()
        name_input.clear()
        name_input.fill(new_name)
        self.get_by_role_button(self._SAVE_BTN).click()
        self.wait_for_loading()

    def delete_profile(self) -> None:
        """Delete the profile via the two-step Danger Zone confirmation.

        Clicks *Delete Scout* (opens a native ``<dialog>``), then *Delete
        Permanently* inside that dialog.  The *Delete Permanently* button
        carries an ``hx-confirm`` which fires a ``window.confirm``; a one-shot
        dialog handler accepts it so the HTMX DELETE request is issued.
        """
        self.get_by_role_button(self._DELETE_SCOUT_BTN).click()
        dialog = self.page.locator(self._DELETE_DIALOG_SEL)
        expect(dialog).to_be_visible(timeout=5_000)
        # Accept the hx-confirm window.confirm before clicking Delete Permanently.
        self.page.once("dialog", lambda dlg: dlg.accept())
        dialog.get_by_role("button", name=self._DELETE_PERM_BTN, exact=True).click()
        # The HTMX delete removes the record from DynamoDB; allow the swap and
        # a brief settle before returning.
        self.wait_for_loading()

    def click_transfer_ownership(self) -> None:
        """Click the Transfer Ownership button (no-op if absent locally)."""
        self.page.get_by_role("button", name=self._TRANSFER_BTN, exact=True).first.click()
        self.wait_for_loading()
