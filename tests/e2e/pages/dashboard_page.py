"""Dashboard page object — seller profile list (Scouts page)."""

import urllib.parse

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class DashboardPage(BasePage):
    """Page object for the ``/scouts`` dashboard route.

    The HTMX Scouts page shows a grid of profile cards (one per seller profile
    the authenticated account owns).  Profile names are rendered as ``<h3>``
    inside ``div.card`` elements with ``id="profile-card-{profileId}"``.

    Selector notes:

    * Profile cards: ``div.card[id^="profile-card-"]``; the seller name is the
      ``<h3>`` inside the card.
    * The *Create Scout* button opens a native ``<dialog>`` (HTMX swap into
      ``#modal-container``).  There are two buttons labelled *Create Scout*
      once the dialog is open — the page button and the dialog submit — so
      callers must scope to the dialog or use ``.first`` for the page button.
    * The *View All Campaigns* action is an ``<a>`` link, but its ``href``
      contains a raw ``PROFILE#uuid`` ID whose ``#`` would be treated as a URL
      fragment by the browser.  ``click_profile`` therefore extracts the
      profile ID from the card ``id`` and navigates via an URL-encoded path.
    """

    PATH: str = "/scouts"

    # ------------------------------------------------------------------
    # Selector constants
    # ------------------------------------------------------------------

    _PROFILE_CARD_SEL: str = "div.card[id^='profile-card-']"
    _PROFILE_NAME_SEL: str = "div.card[id^='profile-card-'] h3"
    _CREATE_SCOUT_TEXT: str = "Create Scout"
    _VIEW_CAMPAIGNS_TEXT: str = "View All Campaigns"
    _EMPTY_STATE_TEXT: str = "No Scouts Yet"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self) -> None:
        """Navigate to ``/scouts`` and wait until the page is ready."""
        self.navigate(self.PATH)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _create_scout_button(self) -> Locator:
        """Return locator for the page-level *Create Scout* button.

        Scoped to the page header (outside any dialog) so the dialog submit
        button is not matched before the dialog opens.
        """
        return (
            self.page.locator("#profiles-list")
            .locator("..")
            .get_by_role("button", name=self._CREATE_SCOUT_TEXT)
            .or_(self.page.get_by_role("button", name=self._CREATE_SCOUT_TEXT).first)
        )

    def _profile_headings(self) -> Locator:
        """Return locator matching all seller-name headings inside profile cards."""
        return self.page.locator(self._PROFILE_NAME_SEL)

    def _profile_card_for(self, name: str) -> Locator:
        """Return a locator for the profile card that contains *name*."""
        return self.page.locator(self._PROFILE_CARD_SEL).filter(has_text=name)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_visible(self) -> bool:
        """Return ``True`` when the dashboard is the current page and ready.

        Checks both the URL and the presence of the *Create Scout* button to
        distinguish a fully loaded dashboard from a transient loading state.
        """
        url_matches = self.PATH in self.page.url
        button_visible = self._create_scout_button().first.is_visible()
        return url_matches and button_visible

    def get_profile_names(self) -> list[str]:
        """Return the text of all visible seller-profile name headings."""
        return self._profile_headings().all_inner_texts()

    def get_profile_id(self, name: str) -> str:
        """Return the raw profile ID (e.g. ``PROFILE#uuid``) for the card matching *name*."""
        card = self._profile_card_for(name).first
        expect(card).to_be_visible()
        card_id = card.get_attribute("id") or ""
        return urllib.parse.unquote(card_id.removeprefix("profile-card-"))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def click_profile(self, name: str) -> None:
        """Navigate to the campaigns page for the profile card matching *name*.

        The card's *View All Campaigns* ``<a>`` link contains a raw
        ``PROFILE#uuid`` ID whose ``#`` the browser treats as a URL fragment,
        so clicking it would land on ``/scouts/PROFILE``.  Instead, extract the
        profile ID from the card ``id`` attribute and navigate via an
        URL-encoded path (which the local server decodes back to the real ID).
        """
        profile_id = self.get_profile_id(name)
        encoded = urllib.parse.quote(profile_id, safe="")
        self.navigate(f"/scouts/{encoded}/campaigns")
        self.wait_for_loading()

    def wait_for_profiles_loaded(self) -> None:
        """Block until the dashboard has finished loading profiles.

        The dashboard is considered loaded when either at least one profile
        card heading is visible, or the empty-state message is visible.
        """
        profile_heading = self._profile_headings().first
        empty_alert = self.page.get_by_text(self._EMPTY_STATE_TEXT)
        expect(profile_heading.or_(empty_alert)).to_be_visible(timeout=15_000)
