"""Profile management page object — edit, delete, and transfer ownership."""

import urllib.parse

from playwright.sync_api import Locator, Page, PlaywrightTimeoutError, expect

from .base_page import BasePage
from .dashboard_page import DashboardPage


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

    def transfer_ownership_button_is_visible(self, timeout: int = 10_000) -> bool:
        """Return True when the Transfer Ownership button is visible and enabled.

        The button only appears in the share table rows (one per existing
        share), so this method returns False when no shares exist. When multiple
        shares exist, the first Transfer Ownership button is checked.

        Shares can take a moment to appear after an invite is accepted in a
        separate browser context, so this method polls briefly.

        Args:
            timeout: Maximum time to wait for the button to appear, in
                milliseconds. Defaults to 10 000.

        Returns:
            ``True`` when at least one visible, enabled Transfer Ownership
            button exists on the page.
        """
        btn = self.page.get_by_role("button", name=self._TRANSFER_BTN, exact=True).first
        try:
            btn.wait_for(state="visible", timeout=timeout)
        except PlaywrightTimeoutError:
            return False
        return btn.is_enabled()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def edit_seller_name(self, new_name: str) -> None:
        """Clear the Seller Name field, type *new_name*, and click Save Changes.

        Waits for the page header to reflect the new name so subsequent
        assertions against the UI are not racing the GraphQL refetch.

        Args:
            new_name: Replacement seller name to save.
        """
        name_input = self._seller_name_input()
        name_input.clear()
        name_input.fill(new_name)
        self.get_by_role_button(self._SAVE_BTN).click()
        self.wait_for_loading()
        expect(self.page.get_by_role("heading", name=f"Scout Management: {new_name}")).to_be_visible(
            timeout=15_000
        )

    def delete_profile(self) -> None:
        """Delete the profile via the two-step Danger Zone confirmation.

        Clicks the *Delete Scout* button which opens a MUI Dialog, then
        clicks *Delete Permanently* inside that dialog, and finally waits
        for the browser to navigate back to the ``/scouts`` dashboard.
        """
        self.get_by_role_button(self._DELETE_SCOUT_BTN).click()
        dialog = self.wait_for_dialog(self._DELETE_DIALOG_TITLE)
        dialog.get_by_role("button", name=self._DELETE_PERM_BTN, exact=True).click()
        self.page.wait_for_url("**/scouts", timeout=20_000)
        self.wait_for_loading()

    def click_transfer_ownership(self) -> None:
        """Click the Transfer Ownership button.

        Playwright auto-dismisses ``window.confirm`` dialogs when no explicit
        handler is set, so this click verifies the button is functional without
        completing the ownership transfer. If multiple shares exist, the first
        Transfer Ownership button is clicked.
        """
        self.page.get_by_role("button", name=self._TRANSFER_BTN, exact=True).first.click()
        self.wait_for_loading()

    def transfer_ownership(self, target_email: str) -> None:
        """Transfer ownership of the current profile to *target_email*.

        Finds the share row containing *target_email*, opens the transfer
        confirmation dialog, confirms, and waits for the redirect back to
        ``/scouts``.

        Args:
            target_email: Email address of the share recipient who will become
                the new owner.
        """
        row = self.page.get_by_role("row").filter(has_text=target_email)
        expect(row.first).to_be_visible(timeout=15_000)
        row.get_by_role("button", name=self._TRANSFER_BTN, exact=True).click()
        dialog = self.wait_for_dialog("Transfer Ownership?")
        dialog.get_by_role("button", name="Transfer", exact=True).click()
        self.page.wait_for_url("**/scouts", timeout=20_000)
        self.wait_for_loading()

    def is_profile_on_dashboard(self, profile_name: str) -> bool:
        """Return ``True`` when *profile_name* is visible on ``/scouts``.

        Navigates to the dashboard, waits for profiles to load, and checks the
        visible profile-card headings.

        Args:
            profile_name: Seller name to look for on the dashboard.
        """
        dashboard = DashboardPage(self.page)
        dashboard.goto()
        dashboard.wait_for_profiles_loaded()
        return profile_name in dashboard.get_profile_names()
