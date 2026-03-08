"""Campaign settings page object — edit name and delete campaign."""

import urllib.parse

from playwright.sync_api import Page

from .base_page import BasePage


class CampaignSettingsPage(BasePage):
    """Page object for ``/scouts/{profileId}/campaigns/{campaignId}/settings``.

    Provides helpers for editing the campaign name and deleting a campaign
    via the confirmation dialog.
    """

    _SETTINGS_SUFFIX: str = "/settings"
    _CAMPAIGN_NAME_LABEL: str = "Campaign Name"
    _SAVE_BTN: str = "Save Changes"
    _DELETE_BTN: str = "Delete Campaign"
    _DELETE_DIALOG_TITLE: str = "Delete Campaign?"
    _CONFIRM_DELETE_BTN: str = "Delete Permanently"

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
    # State queries
    # ------------------------------------------------------------------

    def get_campaign_name(self) -> str:
        """Return the current value of the Campaign Name input field.

        Returns:
            Current text in the campaign name text field.
        """
        return self.page.get_by_label(self._CAMPAIGN_NAME_LABEL).input_value()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def edit_campaign_name(self, new_name: str) -> None:
        """Replace the campaign name and save.

        Clears the current value, fills in *new_name*, then clicks Save Changes.
        Waits for loading spinners to clear before returning.

        Args:
            new_name: Replacement campaign name text.
        """
        name_input = self.page.get_by_label(self._CAMPAIGN_NAME_LABEL)
        name_input.clear()
        name_input.fill(new_name)
        self.get_by_role_button(self._SAVE_BTN).click()
        self.wait_for_loading()

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
