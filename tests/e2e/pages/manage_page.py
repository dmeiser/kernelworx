"""Profile management page object — edit, delete, and transfer ownership."""

import urllib.parse

from playwright.sync_api import Locator, Page

from .base_page import BasePage


class ManagePage(BasePage):
    """Page object for /scouts/{profileId}/manage (ScoutManagementPage).

    Covers profile editing, deletion, and transfer ownership UI.

    Note:
        Invite/sharing actions on the same URL are handled by SharePage.
        This class focuses on the *Edit Profile*, *Delete Profile*, and
        *Transfer Ownership* sections only.
    """

    _MANAGE_SUFFIX: str = "/manage"
    _SELLER_NAME_LABEL: str = "Seller Name"
    _SAVE_BTN: str = "Save Changes"
    #: Button in the Danger Zone that opens the delete-confirmation MUI Dialog.
    _DELETE_SCOUT_BTN: str = "Delete Scout"
    #: Button inside the delete-confirmation MUI Dialog that triggers the actual deletion.
    _DELETE_PERM_BTN: str = "Delete Permanently"
    _DELETE_DIALOG_TITLE: str = "Delete Seller Profile?"
    _TRANSFER_BTN: str = "Transfer Ownership"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance.

        Args:
            page: Active Playwright :class:`~playwright.sync_api.Page`.
        """
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, profile_id: str) -> None:
        """Navigate to the management page for *profile_id*.

        Args:
            profile_id: Raw profile identifier, URL-encoded automatically.
        """
        encoded = urllib.parse.quote(profile_id, safe="")
        self.navigate(f"/scouts/{encoded}{self._MANAGE_SUFFIX}")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _seller_name_input(self) -> Locator:
        """Return locator for the Seller Name text field."""
        return self.page.get_by_label(self._SELLER_NAME_LABEL)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_seller_name(self) -> str:
        """Return current value of the Seller Name input.

        Returns:
            The current text in the Seller Name field.
        """
        return self._seller_name_input().input_value()

    def transfer_ownership_button_is_visible(self) -> bool:
        """Return True when the Transfer Ownership button is visible and enabled.

        The button only appears in the share table rows (one per existing
        share), so this method returns False when no shares exist.

        Returns:
            ``True`` when at least one visible, enabled Transfer Ownership
            button exists on the page.
        """
        btn = self.get_by_role_button(self._TRANSFER_BTN)
        return bool(btn.is_visible() and btn.is_enabled())

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def edit_seller_name(self, new_name: str) -> None:
        """Clear the Seller Name field, type *new_name*, and click Save Changes.

        Args:
            new_name: Replacement seller name to save.
        """
        name_input = self._seller_name_input()
        name_input.clear()
        name_input.fill(new_name)
        self.get_by_role_button(self._SAVE_BTN).click()
        self.wait_for_loading()

    def delete_profile(self) -> None:
        """Delete the profile via the two-step Danger Zone confirmation.

        Clicks the *Delete Scout* button which opens a MUI Dialog, then
        clicks *Delete Permanently* inside that dialog, and finally waits
        for the browser to navigate back to the ``/scouts`` dashboard.
        """
        self.get_by_role_button(self._DELETE_SCOUT_BTN).click()
        dialog = self.wait_for_dialog(self._DELETE_DIALOG_TITLE)
        dialog.get_by_role("button", name=self._DELETE_PERM_BTN, exact=True).click()
        self.page.wait_for_url("**/scouts**", timeout=20_000)
        self.wait_for_loading()

    def click_transfer_ownership(self) -> None:
        """Click the Transfer Ownership button.

        Playwright auto-dismisses ``window.confirm`` dialogs when no explicit
        handler is set, so this click verifies the button is functional without
        completing the ownership transfer.
        """
        self.get_by_role_button(self._TRANSFER_BTN).click()
        self.wait_for_loading()
