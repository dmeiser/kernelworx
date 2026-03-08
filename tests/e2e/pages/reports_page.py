"""Campaign reports page object — verify the reports tab loads."""

import urllib.parse

from playwright.sync_api import Page

from .base_page import BasePage


class ReportsPage(BasePage):
    """Page object for ``/scouts/{profileId}/campaigns/{campaignId}/reports``.

    Provides navigation helpers and visibility checks for the Reports & Exports
    tab of a campaign.
    """

    _REPORTS_SUFFIX: str = "/reports"
    _HEADING_TEXT: str = "Reports & Exports"

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
        """Navigate to the reports tab for the given campaign.

        Args:
            profile_id: Raw profile identifier string.
            campaign_id: Raw campaign identifier string.
        """
        enc_profile = urllib.parse.quote(profile_id, safe="")
        enc_campaign = urllib.parse.quote(campaign_id, safe="")
        self.navigate(f"/scouts/{enc_profile}/campaigns/{enc_campaign}{self._REPORTS_SUFFIX}")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def heading_is_visible(self) -> bool:
        """Return ``True`` when the ``h5`` heading containing 'Reports' is visible.

        Returns:
            ``True`` if the visible heading is present; ``False`` otherwise.
        """
        h5 = self.page.locator("h5", has_text="Reports")
        return bool(h5.first.is_visible())
