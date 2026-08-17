"""Campaign settings page object — edit name and delete campaign."""

import re
import urllib.parse

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class CampaignSettingsPage(BasePage):
    """Page object for ``/scouts/{profileId}/campaigns/{campaignId}/settings``.

    Provides helpers for editing the campaign name, dates, catalog, active
    state, and deleting a campaign via the confirmation dialog.
    """

    _SETTINGS_SUFFIX: str = "/settings"
    _CAMPAIGN_NAME_LABEL: str = "Campaign Name"
    _START_DATE_LABEL: str = "Start Date"
    _END_DATE_LABEL: str = "End Date (Optional)"
    _CATALOG_LABEL: str = "Product Catalog"
    _ACTIVE_LABEL: str = "Campaign is Active"
    _SAVE_BTN: str = "Save Changes"
    _DELETE_BTN: str = "Delete Campaign"
    _DELETE_DIALOG_TITLE: str = "Delete Campaign?"
    _CONFIRM_DELETE_BTN: str = "Delete Permanently"
    _SHARED_CONFIRM_TITLE: str = "Confirm Changes to Shared Campaign"
    _SAVE_ANYWAY_BTN: str = "Save Anyway"

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
        """Navigate to the settings tab for the given campaign.

        Args:
            profile_id: Raw profile identifier string.
            campaign_id: Raw campaign identifier string.
        """
        enc_profile = urllib.parse.quote(profile_id, safe="")
        enc_campaign = urllib.parse.quote(campaign_id, safe="")
        self.navigate(f"/scouts/{enc_profile}/campaigns/{enc_campaign}{self._SETTINGS_SUFFIX}")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _campaign_name_input(self) -> Locator:
        """Return locator for the *Campaign Name* text field."""
        return self.page.get_by_label(self._CAMPAIGN_NAME_LABEL)

    def _start_date_input(self) -> Locator:
        """Return locator for the *Start Date* date field."""
        return self.page.get_by_label(self._START_DATE_LABEL)

    def _end_date_input(self) -> Locator:
        """Return locator for the *End Date (Optional)* date field."""
        return self.page.get_by_label(self._END_DATE_LABEL)

    def _catalog_select(self) -> Locator:
        """Return locator for the *Product Catalog* select.

        MUI ``Select`` renders a visible combobox without an ``aria-label``;
        the label is associated with a hidden input.  Scope the combobox to
        the FormControl containing the *Product Catalog* label.
        """
        return self.page.locator(
            '.MuiFormControl-root:has(label:has-text("Product Catalog")) [role="combobox"]'
        )

    def _active_switch(self) -> Locator:
        """Return locator for the *Campaign is Active* switch."""
        return self.page.get_by_label(self._ACTIVE_LABEL)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_campaign_name(self) -> str:
        """Return the current value of the Campaign Name input field.

        Returns:
            Current text in the campaign name text field.
        """
        return self._campaign_name_input().input_value()

    def get_start_date(self) -> str:
        """Return the current value of the Start Date field.

        Returns:
            ISO date string (yyyy-mm-dd) or empty string.
        """
        return self._start_date_input().input_value()

    def get_end_date(self) -> str:
        """Return the current value of the End Date field.

        Returns:
            ISO date string (yyyy-mm-dd) or empty string.
        """
        return self._end_date_input().input_value()

    def get_selected_catalog_name(self) -> str:
        """Return the visible text of the selected catalog option.

        Returns:
            Catalog name displayed in the Product Catalog select, including
            any type suffix such as ``" (Official)"``.
        """
        select = self._catalog_select()
        # MUI Select can briefly show a zero-width-space placeholder while
        # the campaign query finishes; wait for real text to appear.
        for _ in range(15):
            text = select.inner_text()
            if text and text.strip().replace('\u200b', ''):
                return text
            self.page.wait_for_timeout(200)
        return select.inner_text()

    def get_is_active(self) -> bool:
        """Return ``True`` when the campaign active switch is checked.

        Returns:
            Current checked state of the *Campaign is Active* switch.
        """
        return bool(self._active_switch().is_checked())

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def set_campaign_name(self, new_name: str) -> None:
        """Replace the text in the Campaign Name field without saving.

        Args:
            new_name: Replacement campaign name text.
        """
        name_input = self._campaign_name_input()
        name_input.clear()
        name_input.fill(new_name)

    def edit_campaign_name(self, new_name: str) -> None:
        """Replace the campaign name and save.

        Clears the current value, fills in *new_name*, then clicks Save Changes.
        Waits for loading spinners to clear before returning.

        Args:
            new_name: Replacement campaign name text.
        """
        self.set_campaign_name(new_name)
        self.click_save()

    def set_start_date(self, value: str) -> None:
        """Set the Start Date field to *value*.

        Args:
            value: ISO date string (yyyy-mm-dd).
        """
        date_input = self._start_date_input()
        date_input.clear()
        date_input.fill(value)

    def set_end_date(self, value: str) -> None:
        """Set the End Date field to *value*.

        Args:
            value: ISO date string (yyyy-mm-dd) or empty string.
        """
        date_input = self._end_date_input()
        date_input.clear()
        date_input.fill(value)

    def select_catalog_by_name(self, name: str) -> None:
        """Open the Product Catalog dropdown and select the matching option.

        Matches the visible option text exactly, then falls back to a
        substring match to account for the ``" (Official)"`` suffix on
        admin-managed catalogs.

        Args:
            name: Catalog name to select.

        Raises:
            AssertionError: When no matching catalog option is visible.
        """
        self._catalog_select().click()
        listbox = self.page.get_by_role("listbox")
        expect(listbox).to_be_visible(timeout=5_000)

        option = listbox.get_by_role("option", name=name, exact=True)
        if option.count() == 0:
            option = listbox.locator('[role="option"]').filter(
                has_text=re.compile(re.escape(name))
            ).first

        assert option.count() > 0, f"Catalog option '{name}' not found in dropdown"
        option.click()
        expect(listbox).to_be_hidden(timeout=5_000)

    def toggle_active(self) -> None:
        """Toggle the *Campaign is Active* switch to the opposite state."""
        switch = self._active_switch()
        if switch.is_checked():
            switch.uncheck()
        else:
            switch.check()

    def _wait_for_save_mutation(self) -> None:
        """Wait for the Save button to enter and leave its saving state.

        The button text changes to ``"Saving..."`` while the GraphQL mutation
        is in flight.  Waiting for that state to appear and then disappear
        ensures callers do not reload while an update is still pending.
        """
        saving_button = self.page.get_by_role("button", name="Saving...", exact=True)
        expect(saving_button).to_be_visible(timeout=5_000)
        save_button = self.get_by_role_button(self._SAVE_BTN)
        expect(save_button).to_be_visible(timeout=15_000)
        self.wait_for_loading()

    def click_save(self) -> None:
        """Click the *Save Changes* button and wait for the save to finish.

        For shared campaigns a confirmation dialog opens before the mutation
        actually runs; in that case we return immediately and let the caller
        finish the workflow via :meth:`confirm_shared_campaign_changes`.
        """
        self.get_by_role_button(self._SAVE_BTN).click()

        saving_button = self.page.get_by_role("button", name="Saving...", exact=True)
        dialog = self.page.get_by_role("dialog")
        expect(saving_button.or_(dialog)).to_be_visible(timeout=5_000)
        if dialog.is_visible():
            return

        self._wait_for_save_mutation()

    def confirm_shared_campaign_changes(self) -> None:
        """Confirm the shared-campaign change warning dialog.

        Clicks *Save Anyway* in the ``"Confirm Changes to Shared Campaign"``
        dialog and waits for the save mutation to complete.
        """
        dialog = self.wait_for_dialog(self._SHARED_CONFIRM_TITLE)
        dialog.get_by_role("button", name=self._SAVE_ANYWAY_BTN, exact=True).click()
        self._wait_for_save_mutation()

    def delete_campaign(self) -> None:
        """Open the delete dialog and confirm deletion.

        Clicks the *Delete Campaign* button to open the confirmation dialog,
        then clicks *Delete Permanently* to confirm.  Waits until the browser
        navigates back to the campaigns list URL before returning.
        """
        self.get_by_role_button(self._DELETE_BTN).click()
        dialog = self.wait_for_dialog(self._DELETE_DIALOG_TITLE)
        dialog.get_by_role("button", name=self._CONFIRM_DELETE_BTN).click()
        # After deletion the app navigates back to the campaigns list.
        self.page.wait_for_url("**/campaigns", timeout=20_000)
        self.wait_for_loading()
