"""Fake authentication helpers for the local Playwright e2e suite.

The original helpers performed a real AWS Cognito email/password login against
a deployed dev environment.  The local WSGI test server treats EVERY request
as authenticated (it injects a fixed Cognito ``sub`` claim from the
``x-test-sub`` header, defaulting to ``e2e-test-user-sub``), so no real login
is needed.  These helpers keep the original names and signatures so the smoke
tests do not change their call patterns — they simply navigate to the app.
"""

import os

from playwright.sync_api import Page

from tests.e2e.pages.login_page import LoginPage

#: Base URL of the local WSGI test server.  Set by the ``live_http_server``
#: session fixture in ``conftest.py``; falls back to port 8888 if unset.
_DEFAULT_BASE_URL = "http://127.0.0.1:8888"


def _base_url() -> str:
    """Return the configured base URL for the local app under test."""
    return os.getenv("E2E_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def login(page: Page, email: str | None = None, password: str | None = None) -> None:
    """Navigate to the local app, “authenticated” via the fake server header.

    The local server injects a Cognito ``sub`` claim on every request, so the
    page is already authenticated.  Navigating to ``/scouts`` (rather than
    ``/login``) lands the browser on the authenticated dashboard directly.

    Args:
        page: Active Playwright Page.
        email: Ignored (kept for signature compatibility).
        password: Ignored (kept for signature compatibility).
    """
    page.goto(f"{_base_url()}/scouts")


def login_as_owner(page: Page) -> None:
    """Navigate to the local app as the owner role (fake auth)."""
    login(page)


def login_as_contributor(page: Page) -> None:
    """Navigate to the local app as the contributor role (fake auth)."""
    login(page)


def login_as_readonly(page: Page) -> None:
    """Navigate to the local app as the read-only role (fake auth)."""
    login(page)


def logout(page: Page) -> None:
    """Click the *Sign out* button in the AppBar and wait for the redirect to /login.

    The authenticated app chrome (``base.html``) renders a *Sign out* link that
    calls the ``logout()`` JS helper (``auth.js``), which clears tokens and
    sets ``window.location.href = '/login'``.
    """
    page.goto(f"{_base_url()}/home")
    page.get_by_role("link", name="Sign out").click()
    page.wait_for_url("**/login", timeout=10_000)


def render_login_page(page: Page) -> LoginPage:
    """Navigate to the /login page (unauthenticated render) and return its page object."""
    login_page = LoginPage(page)
    login_page.goto()
    return login_page
