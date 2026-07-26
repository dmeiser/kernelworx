"""Base page object providing common browser interactions for all page objects."""

import pathlib

from playwright.sync_api import Locator, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


class BasePage:
    """Base class for all page objects.

    Wraps a Playwright :class:`~playwright.sync_api.Page` instance and exposes
    shared navigation / interaction helpers used by every page.

    The HTMX app has no MUI CircularProgress spinner; loading is indicated by
    HTMX swap activity.  ``wait_for_loading`` is therefore a short settle wait
    rather than a spinner-poll.
    """

    #: CSS selector for HTMX loading indicators (htmx:indicator / .htmx-indicator).
    _SPINNER: str = ".htmx-indicator"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        self.page = page

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def navigate(self, path: str = "") -> None:
        """Navigate to *path* relative to the local e2e server base URL.

        Args:
            path: URL path to append, e.g. ``"/login"``. Defaults to ``""``.
        """
        import os

        base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8888").rstrip("/")
        self.page.goto(f"{base_url}{path}")

    def wait_for_url_contains(self, fragment: str, timeout: int = 10_000) -> None:
        """Block until the current URL contains *fragment*."""
        self.page.wait_for_url(f"**{fragment}**", timeout=timeout)

    # ------------------------------------------------------------------
    # Wait helpers
    # ------------------------------------------------------------------

    def wait_for_loading(self, timeout: int = 2_000) -> None:
        """Wait briefly for HTMX swaps / page settle.

        The HTMX app does not render MUI spinners; instead it swaps fragments
        in place.  A short wait for any ``.htmx-indicator`` to hide, plus a
        brief DOM-settle, is sufficient.
        """
        indicator = self.page.locator(self._SPINNER)
        try:
            indicator.first.wait_for(state="hidden", timeout=timeout)
        except PlaywrightTimeoutError:
            pass  # no indicator present — that is fine
        # Allow in-flight htmx requests to complete.
        self.page.wait_for_load_state("networkidle", timeout=timeout)

    def wait_for_dialog(self, title: str, timeout: int = 5_000) -> Locator:
        """Wait for a native ``<dialog>`` with the given heading text to be visible.

        The HTMX templates use native ``<dialog open>`` elements (not MUI
        Dialog).  The dialog title is an ``<h2>`` (or ``<h1>``) inside the
        dialog.

        Args:
            title: Exact visible title text of the dialog.
            timeout: Maximum wait in milliseconds. Defaults to 5 000.

        Returns:
            Locator for the open ``<dialog>`` element.
        """
        dialog = self.page.locator("dialog[open]")
        expect(dialog.first).to_be_visible(timeout=timeout)
        expect(dialog.get_by_text(title, exact=True).or_(dialog.get_by_role("heading", name=title))).to_be_visible(
            timeout=timeout
        )
        return dialog.first

    # ------------------------------------------------------------------
    # Interaction helpers
    # ------------------------------------------------------------------

    def get_by_role_button(self, accessible_name: str) -> Locator:
        """Return a :class:`~playwright.sync_api.Locator` for a button by accessible name.

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
        """Return the inner text of the first visible alert-style element.

        The HTMX login page renders a plain ``<div id="login-error">`` for
        errors (no ``role="alert"``).  This helper checks for either a
        ``role="alert"`` element or the ``#login-error`` / ``#signup-error``
        divs.

        Returns:
            Alert text, or ``""`` when no alert is visible.
        """
        for selector in ('[role="alert"]', "#login-error", "#signup-error"):
            loc = self.page.locator(selector).first
            if loc.is_visible():
                return loc.inner_text()
        return ""

    # ------------------------------------------------------------------
    # Debugging helpers
    # ------------------------------------------------------------------

    def screenshot(self, name: str) -> None:
        """Capture a screenshot and write it to ``test-results/<name>.png``."""
        pathlib.Path("test-results").mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=f"test-results/{name}.png")
