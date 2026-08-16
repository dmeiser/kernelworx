"""Home page object — logged-in landing page."""

from playwright.sync_api import Page, expect

from .base_page import BasePage


class HomePage(BasePage):
    """Page object for ``/home``.

    Provides helpers for verifying the logged-in home page and clicking the
    quick-action tiles.
    """

    PATH: str = "/home"

    _MY_SCOUTS_TILE: str = "My Scouts"
    _PAYMENT_METHODS_TILE: str = "Payment Methods"
    _CATALOGS_TILE: str = "Catalogs"
    _SHARED_CAMPAIGNS_TILE: str = "Shared Campaigns"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto(self) -> None:
        """Navigate to ``/home`` and wait for the page to load."""
        self.navigate(self.PATH)
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_visible(self) -> bool:
        """Return ``True`` when the home page heading is visible."""
        heading = self.page.get_by_role("heading", name="Welcome back")
        return heading.first.is_visible()

    def get_welcome_text(self) -> str:
        """Return the full text of the welcome heading.

        Returns:
            Inner text of the welcome heading.
        """
        heading = self.page.get_by_role("heading", name="Welcome back")
        expect(heading).to_be_visible(timeout=10_000)
        return heading.inner_text()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def click_my_scouts(self) -> None:
        """Click the *My Scouts* quick-action tile."""
        self.page.get_by_role("heading", name=self._MY_SCOUTS_TILE).first.click()
        self.wait_for_loading()

    def click_payment_methods(self) -> None:
        """Click the *Payment Methods* quick-action tile."""
        self.page.get_by_role("heading", name=self._PAYMENT_METHODS_TILE).first.click()
        self.wait_for_loading()

    def click_catalogs(self) -> None:
        """Click the *Catalogs* quick-action tile."""
        self.page.get_by_role("heading", name=self._CATALOGS_TILE).first.click()
        self.wait_for_loading()

    def click_shared_campaigns(self) -> None:
        """Click the *Shared Campaigns* quick-action tile."""
        self.page.get_by_role("heading", name=self._SHARED_CAMPAIGNS_TILE).first.click()
        self.wait_for_loading()
