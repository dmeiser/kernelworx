"""Login page object for the HTMX login page (``/login``).

The HTMX login page renders a custom form (``input#email``, ``input#password``,
a *Sign In* submit button) plus *Continue with Google* and *Sign In with
Passkey* options and a *Sign up* link.  The local test server does not wire
``/api/auth/login``, so a real login round-trip is not possible; this page
object exposes the form fields and a ``login`` method for UI-render checks
only.
"""

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class LoginPage(BasePage):
    """Page object for the ``/login`` route."""

    PATH: str = "/login"

    # The HTMX login form uses id-based inputs (the labels are not associated).
    _EMAIL_SEL: str = "input#email"
    _PASSWORD_SEL: str = "input#password"
    _SUBMIT_NAME: str = "Sign In"

    def __init__(self, page: Page) -> None:
        """Store the Playwright Page instance."""
        super().__init__(page)

    def goto(self) -> None:
        """Navigate to ``/login`` and wait for the email field to be visible."""
        self.navigate(self.PATH)
        expect(self._email_input()).to_be_visible()

    # ------------------------------------------------------------------
    # Locator factories
    # ------------------------------------------------------------------

    def _email_input(self) -> Locator:
        """Return locator for the email ``<input>`` element."""
        return self.page.locator(self._EMAIL_SEL)

    def _password_input(self) -> Locator:
        """Return locator for the password ``<input>`` element."""
        return self.page.locator(self._PASSWORD_SEL)

    def _submit_button(self) -> Locator:
        """Return locator for the *Sign In* submit button."""
        return self.get_by_role_button(self._SUBMIT_NAME)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def login(self, email: str, password: str) -> None:
        """Fill and submit the email/password login form.

        Note: the local server does not implement ``/api/auth/login``, so
        submission does not authenticate; this method is used only to verify
        the form is interactive.
        """
        self._email_input().fill(email)
        self._password_input().fill(password)
        self._submit_button().click()

    def wait_for_redirect(self, destination: str = "/home", timeout: int = 5_000) -> None:
        """Block until the browser navigates away to *destination*."""
        self.wait_for_url_contains(destination, timeout=timeout)

    # ------------------------------------------------------------------
    # Assertions / state queries
    # ------------------------------------------------------------------

    def is_logged_in(self) -> bool:
        """Return ``True`` when the browser has left the ``/login`` page."""
        return self.PATH not in self.page.url

    def get_error_message(self) -> str:
        """Return the visible error text, or ``""`` when none is shown."""
        return self.get_visible_alert_text()

    def has_google_button(self) -> bool:
        """Return ``True`` when the *Continue with Google* link is visible."""
        return bool(self.page.get_by_role("link", name="Continue with Google").first.is_visible())

    def has_signup_link(self) -> bool:
        """Return ``True`` when the *Sign up* link is visible."""
        return bool(self.page.get_by_role("link", name="Sign up").first.is_visible())
