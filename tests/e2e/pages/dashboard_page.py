"""Dashboard page object — seller profile list (Scouts page)."""

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class DashboardPage(BasePage):
    """Page object for the ``/scouts`` dashboard route.

    After login users land on the Scouts page, which shows a grid of
    :class:`ProfileCard` components — one per seller profile (Scout) the
    authenticated account owns or has been shared access to.

    Selector notes:

    * Profile names are rendered as ``<h3>`` elements (MUI ``Typography
      variant="h5" component="h3"``).  No ``data-testid`` is present in the
      production component.  TODO: add ``data-testid="profile-card"`` to
      ``ProfileCard`` for more robust targeting.
    * The *Create Scout* button uses visible text; no ``data-testid``.
    * The *View All Campaigns* button on each card uses visible text.
    """

    PATH: str = "/scouts"

    # ------------------------------------------------------------------
    # Selector constants
    # ------------------------------------------------------------------

    # ProfileCard renders sellerName via Typography variant="h5" component="h3"
    _PROFILE_NAME_SEL: str = "div.MuiCard-root h3"  # scoped to cards to avoid dialog collisions

    _CREATE_SCOUT_TEXT: str = "Create Scout"
    _VIEW_CAMPAIGNS_TEXT: str = "View All Campaigns"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance.

        Args:
            page: Active Playwright :class:`~playwright.sync_api.Page`.
        """
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
        """Return locator for the *Create Scout* button."""
        return self.get_by_role_button(self._CREATE_SCOUT_TEXT)

    def _profile_headings(self) -> Locator:
        """Return locator matching all seller-name headings inside profile cards."""
        return self.page.locator(self._PROFILE_NAME_SEL)

    def _profile_card_for(self, name: str) -> Locator:
        """Return a locator for the profile card that contains *name*.

        Args:
            name: Seller name text (case-sensitive substring match).
        """
        return self.page.locator("div.MuiCard-root").filter(has_text=name)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_visible(self) -> bool:
        """Return ``True`` when the dashboard is the current page and ready.

        Checks both the URL and the presence of the *Create Scout* button to
        distinguish a fully loaded dashboard from a transient loading state.
        """
        url_matches = self.PATH in self.page.url
        button_visible = self._create_scout_button().is_visible()
        return url_matches and button_visible

    def get_profile_names(self) -> list[str]:
        """Return the text of all visible seller-profile name headings.

        Returns:
            List of seller name strings in DOM order.
        """
        return self._profile_headings().all_inner_texts()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def click_profile(self, name: str) -> None:
        """Click on the profile card for *name* to navigate to its campaigns.

        Clicks the *View All Campaigns* button within the matching card so the
        action is deterministic even when a *View Latest Campaign* button is
        also present.

        Args:
            name: Exact seller name to match (case-sensitive).
        """
        card = self._profile_card_for(name).first  # take first matching card
        expect(card).to_be_visible()
        card.get_by_role("button", name=self._VIEW_CAMPAIGNS_TEXT, exact=True).click()
        self.wait_for_loading()

    def wait_for_profiles_loaded(self) -> None:
        """Block until at least one profile card heading is visible."""
        expect(self._profile_headings().first).to_be_visible()
