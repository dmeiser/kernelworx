"""Cognito authentication helpers for Playwright e2e tests.

The app uses AWS Cognito via aws-amplify with a custom login page at /login.
Email/password auth is handled by the CredentialsForm component, which renders
standard MUI TextFields (no data-testid attributes) and a submit button.

Selector strategy (in priority order):
  1. data-testid attributes (if they exist in the future)
  2. Standard HTML attribute selectors (input[type="email"], etc.)
"""

import os

from playwright.sync_api import Page

from tests.e2e.pages.login_page import LoginPage


def _require_env(key: str) -> str:
    """Get a required environment variable with a helpful error message."""
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            "Copy .env.example to .env and fill in test user credentials. "
            "See tests/e2e/README.md for setup instructions."
        )
    return value


def _base_url() -> str:
    """Return the configured base URL for the app under test."""
    return os.getenv("E2E_BASE_URL", "https://localhost:5173").rstrip("/")


def login(page: Page, email: str, password: str) -> None:
    """Navigate to the app login page and authenticate with the given credentials.

    Delegates entirely to :class:`~tests.e2e.pages.login_page.LoginPage` so
    that selector logic lives in exactly one place.
    """
    login_page = LoginPage(page)
    login_page.goto()
    login_page.login(email, password)
    login_page.wait_for_redirect()


def login_as_owner(page: Page) -> None:
    """Navigate to the app and log in as the owner test user.

    Credentials are read from TEST_OWNER_EMAIL / TEST_OWNER_PASSWORD env vars.
    """
    email = _require_env("TEST_OWNER_EMAIL")
    password = _require_env("TEST_OWNER_PASSWORD")
    login(page, email, password)


def login_as_contributor(page: Page) -> None:
    """Navigate to the app and log in as the contributor test user.

    Credentials are read from TEST_CONTRIBUTOR_EMAIL / TEST_CONTRIBUTOR_PASSWORD env vars.
    """
    email = _require_env("TEST_CONTRIBUTOR_EMAIL")
    password = _require_env("TEST_CONTRIBUTOR_PASSWORD")
    login(page, email, password)


def login_as_readonly(page: Page) -> None:
    """Navigate to the app and log in as the read-only test user.

    Credentials are read from TEST_READONLY_EMAIL / TEST_READONLY_PASSWORD env vars.
    """
    email = _require_env("TEST_READONLY_EMAIL")
    password = _require_env("TEST_READONLY_PASSWORD")
    login(page, email, password)


def logout(page: Page) -> None:
    """Log out the currently authenticated user.

    Navigates to /settings where the "Sign Out" button lives, clicks it,
    and waits for the redirect back to /login.
    """
    page.goto(f"{_base_url()}/settings")
    # The SettingsPage renders: <Button ... onClick={handleLogout}>Sign Out</Button>
    page.get_by_role("button", name="Sign Out").click()
    page.wait_for_url("**/login", timeout=10_000)
