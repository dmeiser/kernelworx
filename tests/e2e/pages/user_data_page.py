"""User data page object — admin user-data drill-down."""

import re
import urllib.parse

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class UserDataPage(BasePage):
    """Page object for ``/admin/user-data/{accountId}``.

    Covers the Profiles, Catalogs, Campaigns, Shared Campaigns, and Shares
    tabs plus the *Transfer Profile Ownership* and *Revoke Access* dialogs.
    """

    PATH_PREFIX: str = "/admin/user-data"

    # Tabs (labels include dynamic counts, so we match by prefix)
    _PROFILES_TAB_RE: re.Pattern[str] = re.compile(r"^Profiles")
    _CATALOGS_TAB_RE: re.Pattern[str] = re.compile(r"^Catalogs")
    _CAMPAIGNS_TAB_RE: re.Pattern[str] = re.compile(r"^Campaigns")
    _SHARED_CAMPAIGNS_TAB_RE: re.Pattern[str] = re.compile(r"^Shared Campaigns")
    _SHARES_TAB_TEXT: str = "Shares"

    # Section headings
    _PROFILES_HEADING: str = "Seller Profiles"
    _CATALOGS_HEADING: str = "Product Catalogs"
    _CAMPAIGNS_HEADING: str = "Profile Campaigns"
    _SHARED_CAMPAIGNS_HEADING: str = "Shared Campaigns Created by User"
    _SHARES_HEADING: str = "Profile Shares"

    # Empty-state alerts
    _NO_PROFILES_TEXT: str = "No profiles found for this user."
    _NO_CATALOGS_TEXT: str = "No catalogs found for this user."
    _NO_PROFILES_FOR_CAMPAIGNS_TEXT: str = "No profiles to manage campaigns for."
    _NO_CAMPAIGNS_FOR_PROFILE_TEXT: str = "No campaigns found for this profile."
    _NO_SHARED_CAMPAIGNS_TEXT: str = "No shared campaigns found for this user."
    _NO_PROFILES_FOR_SHARES_TEXT: str = "No profiles to manage shares for."
    _NO_SHARES_TEXT: str = "No shares found for this profile."

    # Dialogs
    _TRANSFER_DIALOG_TITLE: str = "Transfer Profile Ownership"
    _NEW_OWNER_EMAIL_LABEL: str = "New Owner Email"
    _SEARCH_NEW_OWNER_LABEL: str = "Search new owner"
    _CONFIRM_TRANSFER_BTN: str = "Confirm Transfer"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, account_id: str) -> None:
        """Navigate to the user-data page for *account_id*.

        Args:
            account_id: Raw account identifier string.
        """
        encoded = urllib.parse.quote(account_id, safe="")
        self.navigate(f"{self.PATH_PREFIX}/{encoded}")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories — tabs
    # ------------------------------------------------------------------

    def _profiles_tab(self) -> Locator:
        """Return locator for the *Profiles* tab."""
        return self.page.get_by_role("tab", name=self._PROFILES_TAB_RE)

    def _catalogs_tab(self) -> Locator:
        """Return locator for the *Catalogs* tab."""
        return self.page.get_by_role("tab", name=self._CATALOGS_TAB_RE)

    def _campaigns_tab(self) -> Locator:
        """Return locator for the *Campaigns* tab."""
        return self.page.get_by_role("tab", name=self._CAMPAIGNS_TAB_RE)

    def _shared_campaigns_tab(self) -> Locator:
        """Return locator for the *Shared Campaigns* tab."""
        return self.page.get_by_role("tab", name=self._SHARED_CAMPAIGNS_TAB_RE)

    def _shares_tab(self) -> Locator:
        """Return locator for the *Shares* tab."""
        return self.page.get_by_role("tab", name=self._SHARES_TAB_TEXT, exact=True)

    # ------------------------------------------------------------------
    # Locator factories — tab panels
    # ------------------------------------------------------------------

    def _tabpanel_heading(self, text: str) -> Locator:
        """Return a section heading inside the active tab panel."""
        return self.page.locator("h6", has_text=text)

    def _data_table(self) -> Locator:
        """Return the first visible data ``<table>`` on the page."""
        return self.page.locator("table").first

    def _wait_for_table_rows(self, timeout: int = 10_000) -> Locator:
        """Return the first data table after at least one row is visible.

        Admin UserData queries use eventually-consistent DynamoDB reads, so
        the table can render before its rows populate. Callers that read cell
        text should wait through this helper to avoid empty lists.
        """
        table = self._data_table()
        expect(table.locator("tbody tr").first).to_be_visible(timeout=timeout)
        return table

    def _profile_button(self, seller_name: str) -> Locator:
        """Return the profile selection button labeled *seller_name*."""
        return self.page.get_by_role("button", name=seller_name, exact=True)

    # ------------------------------------------------------------------
    # Locator factories — transfer dialog
    # ------------------------------------------------------------------

    def _transfer_dialog(self) -> Locator:
        """Return the *Transfer Profile Ownership* dialog locator."""
        return self.page.get_by_role("dialog")

    def _new_owner_email_input(self) -> Locator:
        """Return the *New Owner Email* field inside the transfer dialog."""
        return self.page.get_by_label(self._NEW_OWNER_EMAIL_LABEL)

    def _search_new_owner_button(self) -> Locator:
        """Return the search icon button inside the transfer dialog."""
        return self.page.get_by_role("button", name=self._SEARCH_NEW_OWNER_LABEL, exact=True)

    def _confirm_transfer_button(self) -> Locator:
        """Return the *Confirm Transfer* dialog button."""
        return self.get_by_role_button(self._CONFIRM_TRANSFER_BTN)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_visible(self) -> bool:
        """Return ``True`` when the user-data page heading is visible."""
        return self.page.get_by_text("User Data Management").first.is_visible()

    def profiles_tab_has_content(self) -> bool:
        """Return ``True`` when the Profiles tab heading and data/empty state render."""
        heading = self._tabpanel_heading(self._PROFILES_HEADING)
        empty = self.page.get_by_text(self._NO_PROFILES_TEXT)
        table = self._data_table()
        return bool(heading.first.is_visible() and (empty.first.is_visible() or table.is_visible()))

    def catalogs_tab_has_content(self) -> bool:
        """Return ``True`` when the Catalogs tab heading and data/empty state render."""
        heading = self._tabpanel_heading(self._CATALOGS_HEADING)
        empty = self.page.get_by_text(self._NO_CATALOGS_TEXT)
        table = self._data_table()
        return bool(heading.first.is_visible() and (empty.first.is_visible() or table.is_visible()))

    def _active_tabpanel_buttons(self) -> Locator:
        """Return buttons rendered inside the currently visible tab panel."""
        return self.page.locator('[role="tabpanel"]:not([hidden]) button')

    def campaigns_tab_has_content(self) -> bool:
        """Return ``True`` when the Campaigns tab heading and data/empty state render.

        The tab shows either a "no profiles" alert, profile-selection buttons,
        a "no campaigns" alert for the selected profile, or a campaigns table.
        """
        heading = self._tabpanel_heading(self._CAMPAIGNS_HEADING)
        if not heading.first.is_visible():
            return False

        no_profiles = self.page.get_by_text(self._NO_PROFILES_FOR_CAMPAIGNS_TEXT).first
        no_campaigns = self.page.get_by_text(self._NO_CAMPAIGNS_FOR_PROFILE_TEXT).first
        table = self._data_table()
        has_profile_buttons = self._active_tabpanel_buttons().count() > 0
        return bool(no_profiles.is_visible() or no_campaigns.is_visible() or table.is_visible() or has_profile_buttons)

    def shared_campaigns_tab_has_content(self) -> bool:
        """Return ``True`` when the Shared Campaigns tab heading and data/empty state render."""
        heading = self._tabpanel_heading(self._SHARED_CAMPAIGNS_HEADING)
        empty = self.page.get_by_text(self._NO_SHARED_CAMPAIGNS_TEXT)
        table = self._data_table()
        return bool(heading.first.is_visible() and (empty.first.is_visible() or table.is_visible()))

    def shares_tab_has_content(self) -> bool:
        """Return ``True`` when the Shares tab heading and data/empty state render."""
        heading = self._tabpanel_heading(self._SHARES_HEADING)
        if not heading.first.is_visible():
            return False

        no_profiles = self.page.get_by_text(self._NO_PROFILES_FOR_SHARES_TEXT).first
        no_shares = self.page.get_by_text(self._NO_SHARES_TEXT).first
        table = self._data_table()
        has_profile_buttons = self._active_tabpanel_buttons().count() > 0
        return bool(no_profiles.is_visible() or no_shares.is_visible() or table.is_visible() or has_profile_buttons)

    def transfer_dialog_is_visible(self) -> bool:
        """Return ``True`` when the transfer-ownership dialog is open."""
        dialog = self._transfer_dialog()
        return bool(
            dialog.is_visible() and dialog.get_by_role("heading", name=self._TRANSFER_DIALOG_TITLE).is_visible()
        )

    def get_profile_names(self, timeout: int = 10_000) -> list[str]:
        """Return seller names from the Profiles tab table.

        Waits for at least one row to populate because the underlying admin
        query is eventually consistent.

        Args:
            timeout: Maximum wait in milliseconds for rows to appear.

        Returns:
            List of ``Seller Name`` cell texts in DOM order.
        """
        table = self._wait_for_table_rows(timeout=timeout)
        return table.locator("tbody tr td:nth-child(2)").all_inner_texts()

    def get_catalog_names(self, timeout: int = 10_000) -> list[str]:
        """Return catalog names from the Catalogs tab table.

        Args:
            timeout: Maximum wait in milliseconds for rows to appear.

        Returns:
            List of ``Catalog Name`` cell texts in DOM order.
        """
        table = self._wait_for_table_rows(timeout=timeout)
        return table.locator("tbody tr td:first-child").all_inner_texts()

    def get_campaign_names(self, timeout: int = 10_000) -> list[str]:
        """Return campaign names for the selected profile in the Campaigns tab.

        The Campaigns tab only renders a table after a profile button has been
        selected; this helper returns the first-column texts of the visible
        campaigns table.

        Args:
            timeout: Maximum wait in milliseconds for rows to appear.

        Returns:
            List of ``Campaign Name`` cell texts in DOM order.
        """
        table = self._wait_for_table_rows(timeout=timeout)
        return table.locator("tbody tr td:first-child").all_inner_texts()

    def get_shared_campaign_names(self, timeout: int = 10_000) -> list[str]:
        """Return campaign names from the Shared Campaigns tab table.

        Args:
            timeout: Maximum wait in milliseconds for rows to appear.

        Returns:
            List of ``Campaign Name`` cell texts in DOM order.
        """
        table = self._wait_for_table_rows(timeout=timeout)
        return table.locator("tbody tr td:nth-child(2)").all_inner_texts()

    def get_share_emails(self, timeout: int = 10_000) -> list[str]:
        """Return target-account emails from the Shares tab table.

        The Shares tab only renders a table after a profile button has been
        selected. The first cell also contains a caption with the user's name,
        so we scope to the first direct child (the email typography).

        Args:
            timeout: Maximum wait in milliseconds for rows to appear.

        Returns:
            List of ``User Email`` cell texts in DOM order.
        """
        table = self._wait_for_table_rows(timeout=timeout)
        return table.locator("tbody tr td:first-child > *:first-child").all_inner_texts()

    # ------------------------------------------------------------------
    # Actions — tab switching
    # ------------------------------------------------------------------

    def switch_to_profiles(self) -> None:
        """Click the *Profiles* tab."""
        self._profiles_tab().click()
        self.wait_for_loading()

    def switch_to_catalogs(self) -> None:
        """Click the *Catalogs* tab."""
        self._catalogs_tab().click()
        self.wait_for_loading()

    def switch_to_campaigns(self) -> None:
        """Click the *Campaigns* tab."""
        self._campaigns_tab().click()
        self.wait_for_loading()

    def switch_to_shared_campaigns(self) -> None:
        """Click the *Shared Campaigns* tab."""
        self._shared_campaigns_tab().click()
        self.wait_for_loading()

    def switch_to_shares(self) -> None:
        """Click the *Shares* tab."""
        self._shares_tab().click()
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Actions — profile selection inside Campaigns/Shares tabs
    # ------------------------------------------------------------------

    def select_profile_for_campaigns(self, seller_name: str) -> None:
        """Click the profile button inside the Campaigns tab.

        Args:
            seller_name: Display name of the seller profile to inspect.
        """
        self._profile_button(seller_name).click()
        self.wait_for_loading()

    def select_profile_for_shares(self, seller_name: str) -> None:
        """Click the profile button inside the Shares tab.

        Args:
            seller_name: Display name of the seller profile to inspect.
        """
        self._profile_button(seller_name).click()
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Actions — transfer ownership dialog
    # ------------------------------------------------------------------

    def click_transfer_for_profile(self, profile_id: str) -> None:
        """Open the transfer-ownership dialog for *profile_id*.

        Args:
            profile_id: Raw profile identifier shown in the Profiles table.
        """
        row = self.page.get_by_role("row").filter(has_text=profile_id)
        row.get_by_role("button", name="Transfer", exact=True).click()
        self.wait_for_loading()

    def search_new_owner(self, email: str) -> None:
        """Fill the new-owner email field and submit the search.

        Args:
            email: Email address to search for.
        """
        self._new_owner_email_input().fill(email)
        self._search_new_owner_button().click()
        self.wait_for_loading()

    def select_new_owner(self, email: str) -> None:
        """Select a search-result row matching *email*.

        Args:
            email: Email address of the desired new owner.
        """
        self.page.get_by_text(email).first.click()

    def confirm_transfer(self) -> None:
        """Click *Confirm Transfer* and wait for the dialog to close."""
        dialog = self._transfer_dialog()
        self._confirm_transfer_button().click()
        expect(dialog).to_be_hidden(timeout=15_000)
        self.wait_for_loading()

    def cancel_transfer(self) -> None:
        """Click *Cancel* on the transfer dialog and wait for it to close."""
        dialog = self._transfer_dialog()
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(dialog).to_be_hidden(timeout=10_000)
