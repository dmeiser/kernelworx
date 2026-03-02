"""Base page object providing common browser interactions for all page objects."""

import os
import pathlib

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect


class BasePage:
    """Base class for all page objects.

    Wraps a Playwright :class:`~playwright.sync_api.Page` instance and exposes
    shared navigation / interaction helpers used by every page.

    Usage::

        page_obj = LoginPage(page)
        page_obj.goto()
    """

    #: CSS selector for MUI CircularProgress indicators.
    _SPINNER: str = "[role='progressbar']"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance.

        Args:
            page: Active Playwright :class:`~playwright.sync_api.Page`.
        """
        self.page = page

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def navigate(self, path: str = "") -> None:
        """Navigate to *path* relative to the E2E_BASE_URL environment variable.

        Args:
            path: URL path to append, e.g. ``"/login"``. Defaults to ``""``.
        """
        base_url = os.getenv("E2E_BASE_URL", "https://localhost:5173").rstrip("/")
        self.page.goto(f"{base_url}{path}")

    def wait_for_url_contains(self, fragment: str, timeout: int = 10_000) -> None:
        """Block until the current URL contains *fragment*.

        Uses a Playwright glob pattern so any prefix/suffix is accepted.

        Args:
            fragment: Substring that must appear in ``page.url``.
            timeout: Maximum wait in milliseconds. Defaults to 10 000.
        """
        self.page.wait_for_url(f"**{fragment}**", timeout=timeout)

    # ------------------------------------------------------------------
    # Wait helpers
    # ------------------------------------------------------------------

    def wait_for_loading(self, timeout: int = 15_000) -> None:
        """Wait until all MUI CircularProgress spinners have disappeared.

        If no spinner is ever rendered the function returns immediately.

        Args:
            timeout: Maximum wait in milliseconds. Defaults to 15 000.
        """
        spinner = self.page.locator(self._SPINNER)
        try:
            spinner.first.wait_for(state="hidden", timeout=timeout)
        except PlaywrightTimeoutError:
            pass  # spinner never appeared — that is fine

    def wait_for_dialog(self, title: str, timeout: int = 5_000) -> Locator:
        """Wait for a MUI Dialog with the given title to become visible.

        Args:
            title: Exact accessible dialog title text.
            timeout: Maximum wait in milliseconds. Defaults to 5 000.

        Returns:
            Locator for the dialog element.
        """
        dialog = self.page.get_by_role("dialog")
        expect(dialog).to_be_visible(timeout=timeout)
        expect(dialog.get_by_role("heading", name=title)).to_be_visible(timeout=timeout)
        return dialog

    # ------------------------------------------------------------------
    # Interaction helpers
    # ------------------------------------------------------------------

    def get_by_role_button(self, accessible_name: str) -> Locator:
        """Return a :class:`~playwright.sync_api.Locator` for a button.

        Args:
            accessible_name: ARIA label or visible text of the button.

        Returns:
            Locator scoped to matching ``<button>`` elements.
        """
        return self.page.get_by_role("button", name=accessible_name, exact=True)

    # ------------------------------------------------------------------
    # Alert / feedback helpers
    # ------------------------------------------------------------------

    def get_visible_alert_text(self) -> str:
        """Return the inner text of the first visible ``role="alert"`` element.

        Returns:
            Alert text, or ``""`` when no alert is visible.
        """
        alert = self.page.get_by_role("alert").first
        if alert.is_visible():
            return alert.inner_text()
        return ""

    # ------------------------------------------------------------------
    # Debugging helpers
    # ------------------------------------------------------------------

    def screenshot(self, name: str) -> None:
        """Capture a screenshot and write it to ``test-results/<name>.png``.

        The ``test-results/`` directory is created automatically if absent.

        Args:
            name: Base filename, without extension.
        """
        pathlib.Path("test-results").mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=f"test-results/{name}.png")
