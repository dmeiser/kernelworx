"""Campaign reports page object — verify the reports tab loads.

NOTE: The HTMX redesign does not currently implement a reports page (the
orders page links to ``/campaigns/{id}/reports`` but no route/handler serves
that URL, and there is no *Reports & Exports* heading or CSV/XLSX download
UI).  Tests that rely on this page therefore ``pytest.skip`` with a clear
reason; this page object is retained for API compatibility and future use.
"""

import urllib.parse

from playwright.sync_api import Locator, Page

from .base_page import BasePage


class ReportsPage(BasePage):
    """Page object for ``/scouts/{profileId}/campaigns/{campaignId}/reports``."""

    _REPORTS_SUFFIX: str = "/reports"
    _HEADING_TEXT: str = "Reports"
    _TABLE_HEADING_TEXT: str = "All Orders"
    _DOWNLOAD_CSV_TEXT: str = "CSV"
    _DOWNLOAD_XLSX_TEXT: str = "XLSX"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    def goto(self, profile_id: str, campaign_id: str) -> None:
        """Navigate to the reports tab for the given campaign."""
        enc_profile = urllib.parse.quote(profile_id, safe="")
        enc_campaign = urllib.parse.quote(campaign_id, safe="")
        self.navigate(f"/scouts/{enc_profile}/campaigns/{enc_campaign}{self._REPORTS_SUFFIX}")
        self.wait_for_loading()

    def _download_csv_button(self) -> Locator:
        """Return a locator for the *CSV* download button."""
        return self.page.get_by_role("button", name=self._DOWNLOAD_CSV_TEXT, exact=True)

    def _download_xlsx_button(self) -> Locator:
        """Return a locator for the *XLSX* download button."""
        return self.page.get_by_role("button", name=self._DOWNLOAD_XLSX_TEXT, exact=True)

    def heading_is_visible(self) -> bool:
        """Return ``True`` when a heading containing 'Reports' is visible."""
        h = self.page.locator("h1, h2, h3, h5", has_text=self._HEADING_TEXT)
        return bool(h.first.is_visible())

    def table_heading_is_visible(self) -> bool:
        """Return ``True`` when the *All Orders* section heading is visible."""
        heading = self.page.locator("h2, h6", has_text=self._TABLE_HEADING_TEXT)
        return bool(heading.first.is_visible())

    def table_is_visible(self) -> bool:
        """Return ``True`` when the orders ``<table>`` is visible."""
        table = self.page.locator("table")
        return bool(table.first.is_visible())

    def download_csv_button_is_visible(self) -> bool:
        """Return ``True`` when the *CSV* download button is visible."""
        return bool(self._download_csv_button().is_visible())

    def download_xlsx_button_is_visible(self) -> bool:
        """Return ``True`` when the *XLSX* download button is visible."""
        return bool(self._download_xlsx_button().is_visible())

    def download_csv_button_is_enabled(self) -> bool:
        """Return ``True`` when the *CSV* download button is enabled."""
        return bool(self._download_csv_button().is_enabled())

    def download_xlsx_button_is_enabled(self) -> bool:
        """Return ``True`` when the *XLSX* download button is enabled."""
        return bool(self._download_xlsx_button().is_enabled())

    def click_download_csv(self) -> None:
        """Click the *CSV* download button."""
        self._download_csv_button().click()

    def click_download_xlsx(self) -> None:
        """Click the *XLSX* download button."""
        self._download_xlsx_button().click()
