"""Campaign page object — campaign list and creation for a seller profile."""

import urllib.parse

from playwright.sync_api import Locator, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .base_page import BasePage


class CampaignPage(BasePage):
    """Page object for ``/scouts/{profileId}/campaigns``.

    The HTMX campaigns page lists sales campaigns for a seller profile and
    provides a *New Campaign* button that opens a native ``<dialog>`` (HTMX
    swap of ``fragments/create_campaign_dialog.html`` into ``#modal-container``).

    Selector notes:

    * Campaign cards: ``div.card[id^="campaign-card-"]``; the campaign name is
      the ``<h3>`` inside the card, rendered as ``"{name} {year}"``.
    * The *New Campaign* button is a ``<button>`` in the page header.
    * The create dialog has ``input#name`` (Campaign Name), ``input#year``
      (Year), and a *Create Campaign* submit button.
    * The *View Orders* ``<a>`` link contains a raw ``CAMPAIGN#uuid`` ID; its
      ``#`` is treated as a URL fragment by the browser, so ``click_campaign``
      extracts the campaign ID from the card ``id`` and navigates via an
      URL-encoded path.
    """

    _CAMPAIGNS_SUFFIX: str = "/campaigns"

    # Dialog / form selectors
    _DIALOG_TITLE: str = "New Campaign"
    _CAMPAIGN_NAME_LABEL: str = "Campaign Name"
    _CREATE_CAMPAIGN_BTN: str = "Create Campaign"
    _NEW_CAMPAIGN_BTN: str = "New Campaign"
    _VIEW_ORDERS_BTN: str = "View Orders"

    # Campaign card heading
    _CAMPAIGN_HEADING_SEL: str = "div.card[id^='campaign-card-'] h3"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self, profile_id: str) -> None:
        """Navigate to the campaigns list for *profile_id* (URL-encoded)."""
        encoded = urllib.parse.quote(profile_id, safe="")
        self.navigate(f"/scouts/{encoded}{self._CAMPAIGNS_SUFFIX}")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _new_campaign_button(self) -> Locator:
        """Return locator for the *New Campaign* button in the page header."""
        return self.page.get_by_role("button", name=self._NEW_CAMPAIGN_BTN)

    def _campaign_name_input(self) -> Locator:
        """Return locator for the *Campaign Name* input inside the dialog."""
        return self.page.locator("dialog#create-campaign-dialog input#name")

    def _create_button(self) -> Locator:
        """Return locator for the *Create Campaign* submit button in the dialog."""
        return self.page.locator("#create-campaign-dialog").get_by_role("button", name=self._CREATE_CAMPAIGN_BTN)

    def _campaign_headings(self) -> Locator:
        """Return locator matching all campaign-name ``<h3>`` headings."""
        return self.page.locator(self._CAMPAIGN_HEADING_SEL)

    def _campaign_card_for(self, name: str) -> Locator:
        """Return a locator for the campaign card whose name contains *name*."""
        return self.page.locator("div.card[id^='campaign-card-']").filter(has_text=name)

    def _campaign_id(self, name: str) -> str:
        """Return the raw campaign ID (e.g. ``CAMPAIGN#uuid``) for the card matching *name*."""
        card = self._campaign_card_for(name).first
        expect(card).to_be_visible()
        card_id = card.get_attribute("id") or ""
        return urllib.parse.unquote(card_id.removeprefix("campaign-card-"))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def create_campaign_first_catalog(self, name: str, profile_id: str | None = None) -> None:
        """Open the *New Campaign* dialog, fill *name*, and submit.

        The HTMX create-campaign dialog has no catalog/profile selectors (the
        React page did); the ``profile_id`` and ``catalog`` arguments are
        accepted for signature compatibility but ignored — the dialog posts a
        hidden ``profileId`` derived from the page context.

        Args:
            name: Human-readable campaign name (e.g. ``"Fall 2025"``).
            profile_id: Ignored (kept for signature compatibility).
        """
        self._new_campaign_button().click()
        self._campaign_name_input().wait_for(state="visible", timeout=5_000)
        self._campaign_name_input().fill(name)
        self._create_button().click()
        # The dialog is removed via the hx-on::after-request handler; wait for
        # the new campaign card to appear.
        assert self.has_campaign(name, timeout=15_000), f"Campaign '{name}' must be visible in the list after creation"

    def create_campaign(self, name: str, catalog_name: str | None = None) -> None:
        """Open the *New Campaign* dialog, fill it, and submit (signature-compatible).

        Args:
            name: Campaign name text.
            catalog_name: Ignored (kept for signature compatibility).
        """
        self.create_campaign_first_catalog(name)

    def click_campaign(self, name: str) -> None:
        """Navigate to the orders page for the campaign card whose name contains *name*.

        The card's *View Orders* ``<a>`` link contains a raw ``CAMPAIGN#uuid``
        ID whose ``#`` the browser treats as a URL fragment, so we extract the
        campaign ID from the card ``id`` and navigate via an URL-encoded path.
        """
        campaign_id = self._campaign_id(name)
        # Profile ID is in the current URL (encoded); reuse it for the orders URL.
        import re

        match = re.search(r"/scouts/([^/]+)/campaigns", self.page.url)
        assert match, f"Expected /scouts/{{id}}/campaigns in current URL; got: {self.page.url}"
        profile_id_encoded = match.group(1)
        campaign_encoded = urllib.parse.quote(campaign_id, safe="")
        self.navigate(f"/scouts/{profile_id_encoded}/campaigns/{campaign_encoded}")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def has_campaign(self, name: str, timeout: int = 10_000) -> bool:
        """Return ``True`` when a campaign heading containing *name* is visible."""
        heading = self.page.locator(self._CAMPAIGN_HEADING_SEL, has_text=name)
        try:
            heading.first.wait_for(state="visible", timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            return False

    def get_campaign_names(self) -> list[str]:
        """Return the inner text of all visible campaign headings."""
        return self._campaign_headings().all_inner_texts()

    def new_campaign_button_is_available(self) -> bool:
        """Return ``True`` when the *New Campaign* button is visible and enabled."""
        btn = self._new_campaign_button()
        try:
            return bool(btn.first.is_visible() and btn.first.is_enabled())
        except Exception:  # noqa: BLE001 — button absent
            return False

    def has_access_denied_alert(self) -> bool:
        """Return ``True`` when an access-denied / not-found message is visible.

        The HTMX app has no client-side route protection, but a campaign list
        rendered for a non-existent profile shows the empty-state text
        "No Sales Campaigns Yet".  Treat that as the access-denied signal so
        the boundary test can distinguish "shared profile" from "no profile".
        """
        alert = self.page.get_by_text("No Sales Campaigns Yet")
        return bool(alert.first.is_visible())
