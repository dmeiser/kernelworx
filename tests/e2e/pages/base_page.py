"""Base page object providing common browser interactions for all page objects."""

import os
import pathlib
import time

from playwright.sync_api import Locator, Page, expect


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
        """Wait until all MUI CircularProgress spinners have disappeared and remain hidden.

        Lazy-loaded route components introduce an extra Suspense fallback
        (CircularProgress) after auth state resolves.  A naïve "spinner hidden"
        check can return in the brief gap between the auth spinner disappearing
        and the route spinner appearing, or while a page-level data fetch is
        still in progress.  This helper polls until no spinner is visible for a
        short grace period.

        Args:
            timeout: Maximum wait in milliseconds. Defaults to 15 000.
        """
        spinner = self.page.locator(self._SPINNER)
        deadline = time.monotonic() + timeout / 1000
        hidden_ms = 0
        while time.monotonic() < deadline:
            any_visible = any(element.is_visible() for element in spinner.all())
            if any_visible:
                hidden_ms = 0
            else:
                hidden_ms += 100
                if hidden_ms >= 300:
                    return
            self.page.wait_for_timeout(100)
        # Timeout: loading spinner may still be visible, but proceed so the caller
        # can fail with a meaningful assertion instead of hanging here.

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
