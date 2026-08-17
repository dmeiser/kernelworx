"""Campaign reports page object — aggregated shared-campaign reports."""

from pathlib import Path

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class CampaignReportsPage(BasePage):
    """Page object for ``/campaign-reports``.

    Covers campaign selection, report generation, and the three report views
    (Unit Summary, Seller Report, Order Details) including their export buttons.
    """

    PATH: str = "/campaign-reports"

    # Select / generate
    _SHARED_CAMPAIGN_LABEL: str = "Shared Campaign"
    _GENERATE_REPORT_BTN: str = "Generate Report"

    # View selector
    _UNIT_SUMMARY_BTN: str = "Unit Summary"
    _SELLER_REPORT_BTN: str = "Seller Report"
    _ORDER_DETAILS_BTN: str = "Order Details"

    # Section headings
    _UNIT_OVERVIEW_HEADING: str = "Unit Overview"
    _TOP_SELLERS_HEADING: str = "Top Sellers"
    _SELLER_REPORT_HEADING: str = "Seller Report"
    _ALL_ORDERS_HEADING: str = "All Orders"
    _EXPORT_TO_EXCEL_BTN: str = "Export to Excel"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self) -> None:
        """Navigate to ``/campaign-reports`` and wait for the page to load."""
        self.navigate(self.PATH)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _shared_campaign_select(self) -> Locator:
        """Return the *Shared Campaign* MUI Select combobox."""
        return self.page.get_by_role("combobox", name=self._SHARED_CAMPAIGN_LABEL, exact=True)

    def _generate_report_button(self) -> Locator:
        """Return the *Generate Report* button."""
        return self.get_by_role_button(self._GENERATE_REPORT_BTN)

    def _unit_summary_button(self) -> Locator:
        """Return the *Unit Summary* view button."""
        return self.get_by_role_button(self._UNIT_SUMMARY_BTN)

    def _seller_report_button(self) -> Locator:
        """Return the *Seller Report* view button."""
        return self.get_by_role_button(self._SELLER_REPORT_BTN)

    def _order_details_button(self) -> Locator:
        """Return the *Order Details* view button."""
        return self.get_by_role_button(self._ORDER_DETAILS_BTN)

    def _report_header(self) -> Locator:
        """Return the generated report header card."""
        return self.page.locator("div.MuiPaper-root").filter(has=self.page.locator("h5")).first

    def _section_heading(self, text: str) -> Locator:
        """Return an ``h6`` section heading with the given text."""
        return self.page.locator("h6", has_text=text)

    def _data_table(self) -> Locator:
        """Return the first visible data ``<table>``."""
        return self.page.locator("table").first

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_visible(self) -> bool:
        """Return ``True`` when the campaign-reports page heading is visible."""
        return self.page.get_by_text("Shared Campaign Reports").first.is_visible()

    def can_generate_report(self) -> bool:
        """Return ``True`` when the *Generate Report* button is enabled."""
        btn = self._generate_report_button()
        return bool(btn.is_visible() and btn.is_enabled())

    def report_header_is_visible(self) -> bool:
        """Return ``True`` when the generated report header card is visible."""
        return bool(self._report_header().is_visible())

    def unit_summary_is_visible(self) -> bool:
        """Return ``True`` when Unit Overview cards and Top Sellers table render."""
        overview = self._section_heading(self._UNIT_OVERVIEW_HEADING)
        top_sellers = self._section_heading(self._TOP_SELLERS_HEADING)
        cards_visible = (
            self.page.get_by_text("Total Sellers").first.is_visible()
            and self.page.get_by_text("Total Orders").first.is_visible()
            and self.page.get_by_text("Total Sales").first.is_visible()
        )
        return bool(overview.first.is_visible() and top_sellers.first.is_visible() and cards_visible)

    def seller_report_is_visible(self) -> bool:
        """Return ``True`` when the Seller Report section and table render."""
        heading = self._section_heading(self._SELLER_REPORT_HEADING)
        return bool(heading.first.is_visible() and self._data_table().is_visible())

    def order_details_is_visible(self) -> bool:
        """Return ``True`` when the Order Details section and table render."""
        heading = self._section_heading(self._ALL_ORDERS_HEADING)
        return bool(heading.first.is_visible() and self._data_table().is_visible())

    def get_rollup_value(self, label: str) -> str:
        """Return the numeric/currency value under a Unit Overview label.

        Args:
            label: Visible label text in the Unit Overview cards (e.g.
                ``"Total Sellers"``, ``"Total Orders"``, ``"Total Sales"``).

        Returns:
            The inner text of the associated value element, or ``""`` when the
            label is not visible.
        """
        label_el = self.page.get_by_text(label, exact=True)
        if not label_el.is_visible():
            return ""
        return label_el.locator("xpath=../h4").inner_text()

    def get_top_sellers_row_count(self) -> int:
        """Return the number of data rows in the Top Sellers table."""
        section = self.page.locator("div.MuiPaper-root").filter(
            has=self.page.get_by_role("heading", name=self._TOP_SELLERS_HEADING)
        )
        if not section.is_visible():
            return 0
        rows = section.locator("table tbody tr")
        return rows.count()

    def get_active_table_row_count(self) -> int:
        """Return the number of data rows in the first visible data table."""
        table = self._data_table()
        if not table.is_visible():
            return 0
        return table.locator("tbody tr").count()

    def get_active_table_cell_texts(self, column_header: str) -> list[str]:
        """Return all cell texts for the column matching *column_header*.

        Uses a simple heuristic: finds the first visible table, locates the
        header cell whose text equals *column_header*, and returns the inner
        text of every body cell in that column.

        Args:
            column_header: Exact header text (e.g. ``"Customer Name"``).

        Returns:
            List of body-cell texts for the matching column.
        """
        table = self._data_table()
        if not table.is_visible():
            return []
        headers = table.locator("thead th").all_inner_texts()
        try:
            col_index = headers.index(column_header)
        except ValueError:
            return []
        cells = table.locator(f"tbody tr td:nth-child({col_index + 1})")
        return cells.all_inner_texts()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def select_campaign_by_code(self, code: str) -> None:
        """Open the shared-campaign dropdown and select the option for *code*.

        Args:
            code: Shared campaign short code (the option ``data-value``).
        """
        self._shared_campaign_select().click()
        listbox = self.page.get_by_role("listbox")
        expect(listbox).to_be_visible(timeout=5_000)
        option = listbox.locator(f'[role="option"][data-value="{code}"]')
        expect(option).to_be_visible(timeout=5_000)
        option.click()
        expect(listbox).to_be_hidden(timeout=5_000)
        self.wait_for_loading()

    def generate_report(self) -> None:
        """Click *Generate Report* and wait for the report to load."""
        self._generate_report_button().click()
        self.wait_for_loading()

    def switch_to_unit_summary(self) -> None:
        """Click the *Unit Summary* view button."""
        self._unit_summary_button().click()
        self.wait_for_loading()

    def switch_to_seller_report(self) -> None:
        """Click the *Seller Report* view button."""
        self._seller_report_button().click()
        self.wait_for_loading()

    def switch_to_order_details(self) -> None:
        """Click the *Order Details* view button."""
        self._order_details_button().click()
        self.wait_for_loading()

    def export_seller_report(self) -> None:
        """Click the *Export to Excel* button inside the Seller Report section."""
        section = self.page.locator("div.MuiPaper-root").filter(
            has=self.page.get_by_role("heading", name=self._SELLER_REPORT_HEADING)
        )
        section.get_by_role("button", name=self._EXPORT_TO_EXCEL_BTN, exact=True).click()

    def export_order_details(self) -> None:
        """Click the *Export to Excel* button inside the Order Details section."""
        section = self.page.locator("div.MuiPaper-root").filter(
            has=self.page.get_by_role("heading", name=self._ALL_ORDERS_HEADING)
        )
        section.get_by_role("button", name=self._EXPORT_TO_EXCEL_BTN, exact=True).click()

    def _export_section_download(self, section_heading: str, dest: str | Path) -> Path:
        """Click *Export to Excel* inside *section_heading* and save the download.

        Args:
            section_heading: Heading text of the report section containing the
                export button (e.g. ``"Seller Report"`` or ``"All Orders"``).
            dest: Destination path for the downloaded file.

        Returns:
            The resolved destination path.
        """
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        section = self.page.locator("div.MuiPaper-root").filter(
            has=self.page.get_by_role("heading", name=section_heading)
        )
        button = section.get_by_role("button", name=self._EXPORT_TO_EXCEL_BTN, exact=True)
        with self.page.expect_download() as download_info:
            button.click()
        download = download_info.value
        download.save_as(str(path))
        return path

    def download_seller_report_to(self, path: str | Path) -> Path:
        """Download the Seller Report Excel file to *path*.

        Args:
            path: Destination path for the downloaded file.

        Returns:
            The resolved destination path.
        """
        return self._export_section_download(self._SELLER_REPORT_HEADING, path)

    def download_order_details_to(self, path: str | Path) -> Path:
        """Download the Order Details Excel file to *path*.

        Args:
            path: Destination path for the downloaded file.

        Returns:
            The resolved destination path.
        """
        return self._export_section_download(self._ALL_ORDERS_HEADING, path)
