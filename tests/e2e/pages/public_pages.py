"""Public marketing page objects — landing, privacy policy, and story pages."""

from playwright.sync_api import Page, expect

from .base_page import BasePage


class PublicPages(BasePage):
    """Page object for the public marketing pages.

    Covers the landing page (``/``), privacy policy (``/privacy``), and story
    page (``/story``).  These routes do not require authentication.
    """

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_landing(self) -> None:
        """Navigate to ``/`` and wait for the page to load."""
        self.navigate("/")
        self.wait_for_loading()

    def goto_privacy(self) -> None:
        """Navigate to ``/privacy`` and wait for the page to load."""
        self.navigate("/privacy")
        self.wait_for_loading()

    def goto_story(self) -> None:
        """Navigate to ``/story`` and wait for the page to load."""
        self.navigate("/story")
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def landing_is_visible(self) -> bool:
        """Return ``True`` when a landing-page heading is visible."""
        heading = self.page.get_by_role("heading", name="Use it on your own")
        expect(heading).to_be_visible(timeout=10_000)
        return True

    def privacy_is_visible(self) -> bool:
        """Return ``True`` when the privacy policy heading is visible."""
        heading = self.page.get_by_role("heading", name="Privacy Policy")
        expect(heading).to_be_visible(timeout=10_000)
        return True

    def story_is_visible(self) -> bool:
        """Return ``True`` when the story page heading is visible."""
        heading = self.page.get_by_role("heading", name="The Story of KernelWorx")
        expect(heading).to_be_visible(timeout=10_000)
        return True

    def expect_landing_primary_cta(self) -> None:
        """Assert that the landing page primary CTA button is visible."""
        expect(self.page.get_by_role("button", name="Get started").first).to_be_visible(timeout=10_000)
