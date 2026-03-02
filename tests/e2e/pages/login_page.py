"""Login page object for Cognito username/password authentication."""

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage


class LoginPage(BasePage):
    """Page object for the ``/login`` route.

    The app renders a custom login form backed by AWS Amplify / Cognito.
    This page object drives the *email + password* authentication path only;
    social login (Google, Facebook) and passkey flows are out of scope for
    smoke tests.

    Selector notes:

    * ``input[type="email"]`` – MUI ``TextField`` with ``type="email"``.
      TODO: add ``data-testid="email-input"`` to the production component
      if more specificity is needed later.
    * ``input[type="password"]`` – MUI ``TextField`` with ``type="password"``.
      TODO: add ``data-testid="password-input"`` to the production component.
    * ``button[type="submit"]`` – the *Sign In* button.
    * ``[role="alert"]`` – MUI ``<Alert>`` component used for error messages.
    """

    PATH: str = "/login"

    # ------------------------------------------------------------------
    # Raw selector strings (no data-testid in production component yet)
    # ------------------------------------------------------------------

    _EMAIL_SEL: str = 'input[type="email"]'  # TODO: verify selector
    _PASSWORD_SEL: str = 'input[type="password"]'  # TODO: verify selector
    _SUBMIT_NAME: str = "Sign In"

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
        """Navigate to ``/login`` and wait for the email field to be visible."""
        self.navigate(self.PATH)
        expect(self._email_input()).to_be_visible()

    # ------------------------------------------------------------------
    # Locator factories — keep logic in one place for easy maintenance
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

        Args:
            email: User email address.
            password: User account password.
        """
        self._email_input().fill(email)
        self._password_input().fill(password)
        self._submit_button().click()

    def wait_for_redirect(self, destination: str = "/scouts", timeout: int = 15_000) -> None:
        """Block until the browser navigates away to *destination*.

        Args:
            destination: URL fragment expected after successful login.
            timeout: Maximum wait in milliseconds. Defaults to 15 000.
        """
        self.wait_for_url_contains(destination, timeout=timeout)

    # ------------------------------------------------------------------
    # Assertions / state queries
    # ------------------------------------------------------------------

    def is_logged_in(self) -> bool:
        """Return ``True`` when the browser has left the ``/login`` page."""
        return self.PATH not in self.page.url

    def get_error_message(self) -> str:
        """Return the visible error alert text, or ``""`` when none is shown.

        The login page uses a MUI ``<Alert severity="error">`` for both
        Amplify authentication errors and front-end validation messages.
        """
        return self.get_visible_alert_text()
