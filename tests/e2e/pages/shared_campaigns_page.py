"""Shared campaigns page object — create, list, edit, and join shared campaigns."""

import re
import uuid

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class SharedCampaignsPage(BasePage):
    """Page object for ``/shared-campaigns`` and ``/shared-campaigns/create``.

    Covers the shared-campaign list, creation flow, and short-link campaign
    creation (join) flow at ``/c/{sharedCampaignCode}``.
    """

    PATH: str = "/shared-campaigns"
    CREATE_PATH: str = "/shared-campaigns/create"

    # List page
    _CREATE_SHARED_CAMPAIGN_BTN: str = "Create Shared Campaign"
    _CREATE_FIRST_BTN: str = "Create Your First Shared Campaign"
    _DEACTIVATE_BTN: str = "Deactivate"
    _EDIT_BTN: str = "Edit"
    _COPY_LINK_BTN: str = "Copy link"
    _QR_CODE_BTN: str = "View QR code"

    # Create page
    _SELECT_CATALOG_LABEL: str = "Select Catalog"
    _CAMPAIGN_NAME_LABEL: str = "Campaign Name"
    _CAMPAIGN_YEAR_LABEL: str = "Campaign Year"
    _UNIT_TYPE_LABEL: str = "Unit Type"
    _UNIT_NUMBER_LABEL: str = "Unit Number"
    _CITY_LABEL: str = "City"
    _STATE_LABEL: str = "State"
    _SUBMIT_BTN: str = "Create Shared Campaign"

    # Edit dialog
    _EDIT_DIALOG_TITLE: str = "Edit Campaign SharedCampaign"
    _SAVE_CHANGES_BTN: str = "Save Changes"

    # Confirm dialogs
    _DEACTIVATE_CONFIRM_BTN: str = "Deactivate"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self) -> None:
        """Navigate to ``/shared-campaigns`` and wait for the header."""
        self.navigate(self.PATH)
        self.wait_for_loading()
        # The header is always rendered once data (or the empty state) is ready.
        expect(self.page.get_by_role("heading", name="My Shared Campaigns")).to_be_visible(
            timeout=15_000
        )

    def goto_create(self) -> None:
        """Navigate to ``/shared-campaigns/create`` and wait for loading."""
        self.navigate(self.CREATE_PATH)
        self.wait_for_loading()

    def goto_short_link(self, code: str) -> None:
        """Navigate to the short link ``/c/{code}``.

        Args:
            code: Shared campaign short code.
        """
        self.navigate(f"/c/{code}")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories — list page
    # ------------------------------------------------------------------

    def _create_button(self) -> Locator:
        """Return locator for the header *Create Shared Campaign* button."""
        return self.get_by_role_button(self._CREATE_SHARED_CAMPAIGN_BTN)

    def _create_first_button(self) -> Locator:
        """Return locator for the empty-state *Create Your First Shared Campaign* button."""
        return self.get_by_role_button(self._CREATE_FIRST_BTN)

    def _campaign_row(self, code: str) -> Locator:
        """Return a table row locator containing *code*.

        Args:
            code: Shared campaign short code.
        """
        return self.page.get_by_role("row").filter(has_text=code)

    def _edit_button_for_code(self, code: str) -> Locator:
        """Return the edit icon button for the row containing *code*."""
        return self._campaign_row(code).locator('[aria-label="Edit"]')

    def _deactivate_button_for_code(self, code: str) -> Locator:
        """Return the deactivate icon button for the row containing *code*."""
        return self._campaign_row(code).locator('[aria-label="Deactivate"]')

    # ------------------------------------------------------------------
    # Locator factories — create page
    # ------------------------------------------------------------------

    def _catalog_select(self) -> Locator:
        """Return locator for the *Select Catalog* combobox.

        MUI Select does not expose a usable accessible name for this field in
        the current build, so we scope to the FormControl containing the label.
        """
        return self.page.locator("div.MuiFormControl-root").filter(
            has_text=self._SELECT_CATALOG_LABEL
        ).get_by_role("combobox")

    def _campaign_name_input(self) -> Locator:
        """Return locator for the *Campaign Name* field."""
        return self.page.get_by_label(self._CAMPAIGN_NAME_LABEL)

    def _campaign_year_input(self) -> Locator:
        """Return locator for the *Campaign Year* field."""
        return self.page.get_by_label(self._CAMPAIGN_YEAR_LABEL)

    def _unit_type_select(self) -> Locator:
        """Return locator for the *Unit Type* select."""
        return self.page.locator("div.MuiFormControl-root").filter(
            has_text=self._UNIT_TYPE_LABEL
        ).get_by_role("combobox")

    def _unit_number_input(self) -> Locator:
        """Return locator for the *Unit Number* field."""
        return self.page.get_by_label(self._UNIT_NUMBER_LABEL)

    def _city_input(self) -> Locator:
        """Return locator for the *City* field."""
        return self.page.get_by_label(self._CITY_LABEL)

    def _state_input(self) -> Locator:
        """Return locator for the State autocomplete input."""
        return self.page.locator("div.MuiFormControl-root").filter(
            has_text=self._STATE_LABEL
        ).get_by_role("combobox")

    def _submit_button(self) -> Locator:
        """Return locator for the *Create Shared Campaign* submit button."""
        return self.get_by_role_button(self._SUBMIT_BTN)

    # ------------------------------------------------------------------
    # Locator factories — edit dialog
    # ------------------------------------------------------------------

    def _description_input(self) -> Locator:
        """Return locator for the *Description* field in the edit dialog."""
        return self.page.get_by_label("Description (For Your Reference)")

    def _save_changes_button(self) -> Locator:
        """Return locator for the *Save Changes* button in the edit dialog."""
        return self.get_by_role_button(self._SAVE_CHANGES_BTN)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def has_shared_campaign(self, code: str) -> bool:
        """Return ``True`` when a row for *code* is visible in the list.

        Args:
            code: Shared campaign short code.
        """
        return self._campaign_row(code).first.is_visible()

    def get_visible_codes(self, timeout: int = 10_000) -> list[str]:
        """Return the visible short codes from the shared campaigns table.

        Waits for at least one short-code cell to appear so callers that create
        a shared campaign and immediately read the list do not see an empty
        result while the GraphQL query refetches.

        Args:
            timeout: Maximum wait in milliseconds. Defaults to 10 000.

        Returns:
            List of short-code strings in DOM order.
        """
        cells = self.page.get_by_role("cell").filter(has_text=re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)+$"))
        try:
            expect(cells.first).to_be_visible(timeout=timeout)
        except PlaywrightTimeoutError:
            return []
        return cells.all_inner_texts()

    def get_code_by_campaign_name(self, campaign_name: str) -> str | None:
        """Return the short code for the shared-campaign row with *campaign_name*.

        Args:
            campaign_name: Visible campaign name in the shared campaigns table.

        Returns:
            The short-code string, or ``None`` when no matching row is found.
        """
        row = self.page.get_by_role("row").filter(has_text=campaign_name)
        if row.count() == 0:
            return None
        code_cell = row.first.get_by_role("cell").filter(
            has_text=re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)+$")
        )
        if code_cell.count() == 0:
            return None
        return code_cell.first.inner_text().strip()

    # ------------------------------------------------------------------
    # Actions — list page
    # ------------------------------------------------------------------

    def click_create(self) -> None:
        """Click the create button, handling either the header or empty-state variant."""
        header_btn = self._create_button()
        empty_btn = self._create_first_button()
        # Both buttons can be visible when the list is empty (header + empty-state),
        # so scope the visibility expectation to the first match.
        expect(header_btn.or_(empty_btn).first).to_be_visible(timeout=15_000)
        if header_btn.is_visible() and header_btn.is_enabled():
            header_btn.click()
        elif empty_btn.is_visible():
            empty_btn.click()
        else:
            # Fallback: navigate directly if the button is disabled (e.g. max reached).
            self.goto_create()
            return
        self.page.wait_for_url("**/shared-campaigns/create", timeout=10_000)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Actions — create page
    # ------------------------------------------------------------------

    def _select_first_option(self, combobox: Locator) -> None:
        """Open *combobox* and click the first enabled option.

        Args:
            combobox: Playwright locator for the MUI Select combobox.
        """
        combobox.click()
        listbox = self.page.get_by_role("listbox")
        expect(listbox).to_be_visible(timeout=5_000)
        option = listbox.locator('[role="option"]:not([aria-disabled="true"])').first
        expect(option).to_be_visible(timeout=5_000)
        option.click()
        expect(listbox).to_be_hidden(timeout=5_000)

    def create_shared_campaign(
        self,
        catalog_name: str | None = None,
        campaign_name: str | None = None,
    ) -> str:
        """Fill and submit the shared-campaign creation form.

        Args:
            catalog_name: Optional catalog name to select. When omitted, the first
                catalog option is selected.
            campaign_name: Optional campaign name. A unique name is generated when omitted.

        Returns:
            The campaign name used on the form.
        """
        name = campaign_name or f"E2E Shared {uuid.uuid4().hex[:8]}"

        self._catalog_select().click()
        listbox = self.page.get_by_role("listbox")
        expect(listbox).to_be_visible(timeout=5_000)

        enabled_options = listbox.locator('[role="option"]:not([aria-disabled="true"])')
        expect(enabled_options).not_to_have_count(0, timeout=5_000)

        if catalog_name:
            option = listbox.get_by_role("option", name=catalog_name)
            if option.count() == 0:
                option = enabled_options.first
        else:
            option = enabled_options.first

        expect(option).to_be_visible(timeout=5_000)
        option.click()
        expect(listbox).to_be_hidden(timeout=5_000)

        self._campaign_name_input().fill(name)
        self._campaign_year_input().fill(str(2026))

        self._unit_type_select().click()
        unit_listbox = self.page.get_by_role("listbox")
        expect(unit_listbox).to_be_visible(timeout=5_000)
        unit_listbox.locator('[data-value="Pack"]').click()
        expect(unit_listbox).to_be_hidden(timeout=5_000)

        self._unit_number_input().fill("123")
        self._city_input().fill("Lexington")
        self._state_input().fill("KY")

        self._submit_button().click()
        self.page.wait_for_url("**/shared-campaigns", timeout=15_000)
        self.wait_for_loading()
        return name

    # ------------------------------------------------------------------
    # Actions — edit / deactivate
    # ------------------------------------------------------------------

    def edit_description(self, code: str, new_description: str) -> None:
        """Open the edit dialog for *code* and update its description.

        Args:
            code: Shared campaign short code.
            new_description: New description text.
        """
        self._edit_button_for_code(code).click()
        dialog = self.wait_for_dialog(self._EDIT_DIALOG_TITLE)

        desc_input = self._description_input()
        desc_input.clear()
        desc_input.fill(new_description)

        self._save_changes_button().click()
        expect(dialog).to_be_hidden(timeout=15_000)
        self.wait_for_loading()

    def deactivate_shared_campaign(self, code: str) -> None:
        """Deactivate the shared campaign with *code*.

        Args:
            code: Shared campaign short code.
        """
        self._deactivate_button_for_code(code).click()
        dialog = self.wait_for_dialog("Deactivate Shared Campaign?")
        dialog.get_by_role("button", name=self._DEACTIVATE_CONFIRM_BTN, exact=True).click()
        expect(dialog).to_be_hidden(timeout=15_000)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Actions — join via short link
    # ------------------------------------------------------------------

    def join_shared_campaign(self, code: str, profile_id: str | None = None) -> None:
        """Use a short link to create a campaign from a shared campaign.

        Args:
            code: Shared campaign short code.
            profile_id: Optional profile ID to select. When omitted, the first
                enabled profile option is selected.
        """
        self.goto_short_link(code)

        # Select profile
        profile_select = self.page.get_by_role("combobox", name="Select Profile")
        profile_select.click()
        profile_listbox = self.page.get_by_role("listbox")
        expect(profile_listbox).to_be_visible(timeout=5_000)

        enabled_options = profile_listbox.locator('[role="option"]:not([aria-disabled="true"])')
        expect(enabled_options).not_to_have_count(0, timeout=5_000)

        option = enabled_options.first
        if profile_id:
            candidate_ids = {profile_id}
            if not profile_id.startswith("PROFILE#"):
                candidate_ids.add(f"PROFILE#{profile_id}")
            for candidate in candidate_ids:
                candidate_option = profile_listbox.locator(f'[role="option"][data-value="{candidate}"]')
                if candidate_option.count() > 0:
                    option = candidate_option
                    break

        expect(option).to_be_visible(timeout=5_000)
        option.click()
        expect(profile_listbox).to_be_hidden(timeout=5_000)

        submit = self.get_by_role_button("Create Campaign")
        expect(submit).to_be_enabled(timeout=5_000)
        submit.click()

        self.page.wait_for_url("**/campaigns/**", timeout=15_000)
        self.wait_for_loading()
