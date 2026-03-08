"""Campaign page object — campaign list and creation for a seller profile."""

import urllib.parse

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class CampaignPage(BasePage):
    """Page object for ``/scouts/{profileId}/campaigns``.

    Shows the list of sales campaigns for a seller profile and provides
    a *New Campaign* button that opens :class:`CreateCampaignDialog`.

    Selector notes:

    * Campaign names are in ``<h3>`` elements (MUI ``Typography variant="h6"
      component="h3"``), rendered as ``"{campaignName} {campaignYear}"``.
    * All interactive elements use visible-text or ARIA-role selectors because
      the production components have no ``data-testid`` attributes.
      TODO: add ``data-testid="campaign-card"`` to ``CampaignCard``.
    """

    _CAMPAIGNS_SUFFIX: str = "/campaigns"

    # Dialog selectors
    _DIALOG_TITLE: str = "Create New Sales Campaign"  # dialog heading
    _CAMPAIGN_NAME_LABEL: str = "Campaign Name"
    _CATALOG_LABEL: str = "Product Catalog"  # used in CreateCampaignDialog
    _PAGE_CATALOG_LABEL: str = "Select Catalog"  # used in /create-campaign page (CatalogSection)
    _PAGE_PROFILE_LABEL: str = "Select Profile"  # used in /create-campaign page
    _VIEW_ORDERS_BTN: str = "View Orders"  # used in CampaignCard actions
    _CREATE_CAMPAIGN_BTN: str = "Create Campaign"
    _NEW_CAMPAIGN_BTN: str = "New Campaign"

    # Campaign card: Typography variant="h6" component="h3"
    _CAMPAIGN_HEADING_SEL: str = "div.MuiCard-root h3"  # scoped to cards to avoid dialog collisions

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
        """Navigate to the campaigns list for *profile_id*.

        The profile ID is URL-encoded so IDs containing ``#`` (e.g.
        ``PROFILE#uuid``) are transmitted correctly.

        Args:
            profile_id: Raw profile identifier string.
        """
        encoded = urllib.parse.quote(profile_id, safe="")
        self.navigate(f"/scouts/{encoded}{self._CAMPAIGNS_SUFFIX}")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _new_campaign_button(self) -> Locator:
        """Return locator for the *New Campaign* button in the page header."""
        return self.get_by_role_button(self._NEW_CAMPAIGN_BTN)

    def _campaign_name_input(self) -> Locator:
        """Return locator for the *Campaign Name* text field inside the dialog."""
        return self.page.get_by_label(self._CAMPAIGN_NAME_LABEL)

    def _catalog_select(self) -> Locator:
        """Return locator for the *Product Catalog* select inside the dialog."""
        # MUI Select renders a <div role="combobox"> labelled by the InputLabel
        return self.page.get_by_role("combobox", name=self._CATALOG_LABEL)

    def _create_button(self) -> Locator:
        """Return locator for the *Create Campaign* confirm button in the dialog."""
        return self.get_by_role_button(self._CREATE_CAMPAIGN_BTN)

    def _campaign_headings(self) -> Locator:
        """Return locator matching all campaign-name ``<h3>`` headings."""
        return self.page.locator(self._CAMPAIGN_HEADING_SEL)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def create_campaign_first_catalog(self, name: str) -> None:
        """Open the *New Campaign* dialog, fill *name*, pick the first catalog, and submit.

        Encapsulates the full creation flow so test helpers do not need access
        to private locator methods.  Waits for the dialog to close before
        returning.

        Raises:
            AssertionError: When the catalog dropdown opens with no options,
                meaning no catalog exists in the dev environment.  An admin
                must create at least one catalog before running e2e tests.
                See ``tests/e2e/README.md`` for prerequisites.

        Args:
            name: Human-readable campaign name (e.g. ``"Fall 2025"``).
        """
        # Save campaigns URL to return after the page-based creation flow.
        campaigns_url = self.page.url
        self._new_campaign_button().click()
        # New Campaign now navigates to /create-campaign page (not a dialog).
        self.page.wait_for_url("**/create-campaign**", timeout=10_000)
        self.wait_for_loading()
        self._campaign_name_input().fill(name)
        # Select the first available profile (required when >1 profile exists; auto-selected only for 1).
        profile_combobox = self.page.get_by_role("combobox", name=self._PAGE_PROFILE_LABEL)
        profile_combobox.click()
        profile_listbox = self.page.get_by_role("listbox")
        if profile_listbox.is_visible():
            profile_options = profile_listbox.locator('[role="option"]:not([aria-disabled="true"])')
            if profile_options.count() > 0:
                profile_options.first.click()
        self.wait_for_loading()
        catalog_combobox = self.page.get_by_role("combobox", name=self._PAGE_CATALOG_LABEL)
        catalog_combobox.click()
        listbox = self.page.get_by_role("listbox")
        expect(listbox).to_be_visible(timeout=5_000)
        enabled_options = listbox.locator('[role="option"]:not([aria-disabled="true"])')
        assert enabled_options.count() > 0, (
            "No enabled catalog options found in dev environment. "
            "An admin must create at least one catalog before running e2e tests. "
            "See tests/e2e/README.md for prerequisites."
        )
        enabled_options.first.click()
        self._create_button().click()
        # After success the app navigates to the campaign detail page.
        self.page.wait_for_url("**/campaigns/**", timeout=15_000)
        # Navigate back to the campaigns list so has_campaign() can verify.
        self.page.goto(campaigns_url)
        self.wait_for_loading()

    def create_campaign(self, name: str, catalog_name: str) -> None:
        """Open the *New Campaign* dialog, fill it, and submit.

        Waits for the dialog to close before returning so callers can
        immediately call :meth:`has_campaign`.

        Args:
            name: Human-readable campaign name (e.g. ``"Fall 2025"``).
            catalog_name: Visible text of the catalog option to select.
        """
        self._new_campaign_button().click()
        self._fill_campaign_dialog(name, catalog_name)

    def _fill_campaign_dialog(self, name: str, catalog_name: str) -> None:
        """Fill and submit the *Create Campaign* dialog.

        Extracted to keep :meth:`create_campaign` under complexity budget.

        Args:
            name: Campaign name text.
            catalog_name: Catalog option visible text.
        """
        dialog = self.wait_for_dialog("New Campaign")
        self._campaign_name_input().fill(name)
        self._select_catalog(catalog_name)
        self._create_button().click()
        expect(dialog).to_be_hidden(timeout=10_000)
        self.wait_for_loading()

    def _select_catalog(self, catalog_name: str) -> None:
        """Open the catalog dropdown and pick the option matching *catalog_name*.

        Raises:
            AssertionError: When the dropdown opens with no options, which
                means no catalog has been created in the dev environment yet.

        Args:
            catalog_name: Visible text of the catalog menu item.
        """
        self._catalog_select().click()
        options = self.page.get_by_role("option")
        assert options.count() > 0, (
            "No catalogs found in dev environment. "
            "An admin must create at least one catalog before running e2e tests. "
            "See tests/e2e/README.md for prerequisites."
        )
        self.page.get_by_role("option", name=catalog_name).click()

    def click_campaign(self, name: str) -> None:
        """Click on the campaign card whose name contains *name*.

        Clicks the *View Orders* button within the matching card so the action
        is deterministic even when the card itself is not directly clickable.

        Args:
            name: Substring of the campaign name to match.
        """
        card = self.page.locator("div.MuiCard-root").filter(has_text=name).first
        expect(card).to_be_visible()
        card.get_by_role("button", name=self._VIEW_ORDERS_BTN, exact=True).click()
        self.page.wait_for_url("**/campaigns/**", timeout=10_000)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def has_campaign(self, name: str) -> bool:
        """Return ``True`` when a campaign heading containing *name* is visible.

        Args:
            name: Substring to search for in campaign card headings.
        """
        heading = self.page.locator(self._CAMPAIGN_HEADING_SEL, has_text=name)
        return heading.first.is_visible()

    def get_campaign_names(self) -> list[str]:
        """Return the inner text of all visible campaign headings.

        Returns:
            List of ``"{campaignName} {campaignYear}"`` strings, or an empty
            list when no campaigns are present.
        """
        return self._campaign_headings().all_inner_texts()

    def new_campaign_button_is_available(self) -> bool:
        """Return ``True`` when the *New Campaign* button is visible and enabled.

        Returns ``False`` when the button is absent from the DOM, hidden, or
        disabled — any of which indicates the current user does not have write
        access to this campaigns list (e.g. they hold a READ-only share).

        Returns:
            ``True`` if the button is both visible and enabled; ``False`` otherwise.
        """
        btn = self._new_campaign_button()
        return bool(btn.is_visible() and btn.is_enabled())

    def has_access_denied_alert(self) -> bool:
        """Return ``True`` when the page shows the access-denied error alert.

        The ``ScoutCampaignsPage`` React component renders an MUI ``<Alert>``
        with the text "Profile not found or you don't have access to this
        profile." when the API returns an authorization error (no share or not
        the owner).  The URL does **not** change in this state; the caller
        should not rely on a redirect.

        Returns:
            ``True`` if the error alert is currently visible; ``False`` otherwise.
        """
        alert = self.page.get_by_text("Profile not found or you don't have access to this profile.")
        return bool(alert.is_visible())
