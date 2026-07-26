"""Campaign settings page object — edit name and delete campaign.

NOTE: The HTMX redesign does not currently render a campaign settings page or
expose a campaign-delete UI (campaign cards only have a *View Orders* link and
the orders page has a *Settings* tab link to ``/campaigns/{id}/settings``, but
no route/handler serves that URL).  Tests that rely on this page therefore
``pytest.skip`` with a clear reason; this page object is retained for API
compatibility and future use.
"""

import urllib.parse

from playwright.sync_api import Page

from .base_page import BasePage


class CampaignSettingsPage(BasePage):
    """Page object for ``/scouts/{profileId}/campaigns/{campaignId}/settings``."""

    _SETTINGS_SUFFIX: str = "/settings"
    _CAMPAIGN_NAME_LABEL: str = "Campaign Name"
    _SAVE_BTN: str = "Save Changes"
    _DELETE_BTN: str = "Delete Campaign"
    _DELETE_DIALOG_TITLE: str = "Delete Campaign?"
    _CONFIRM_DELETE_BTN: str = "Delete Permanently"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    def goto(self, profile_id: str, campaign_id: str) -> None:
        """Navigate to the settings tab for the given campaign."""
        enc_profile = urllib.parse.quote(profile_id, safe="")
        enc_campaign = urllib.parse.quote(campaign_id, safe="")
        self.navigate(f"/scouts/{enc_profile}/campaigns/{enc_campaign}{self._SETTINGS_SUFFIX}")
        self.wait_for_loading()

    def get_campaign_name(self) -> str:
        """Return the current value of the Campaign Name input field (if present)."""
        return self.page.get_by_label(self._CAMPAIGN_NAME_LABEL).input_value()

    def edit_campaign_name(self, new_name: str) -> None:
        """Replace the campaign name and save."""
        name_input = self.page.get_by_label(self._CAMPAIGN_NAME_LABEL)
        name_input.clear()
        name_input.fill(new_name)
        self.get_by_role_button(self._SAVE_BTN).click()
        self.wait_for_loading()

    def delete_campaign(self) -> None:
        """Open the delete dialog and confirm deletion."""
        self.get_by_role_button(self._DELETE_BTN).click()
        dialog = self.wait_for_dialog(self._DELETE_DIALOG_TITLE)
        dialog.get_by_role("button", name=self._CONFIRM_DELETE_BTN).click()
        self.page.wait_for_url("**/campaigns", timeout=20_000)
        self.wait_for_loading()
