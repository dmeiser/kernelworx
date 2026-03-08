"""Smoke tests for authentication: login, invalid credentials, and logout."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.login_page import LoginPage
from tests.e2e.utils.auth import logout


@pytest.mark.smoke
def test_login_success(owner_page: Page) -> None:
    """Verify the owner can log in and the dashboard (``/scouts``) is visible.

    The ``owner_page`` fixture handles navigation and authentication; this test
    only asserts that the resulting page is the authenticated dashboard.
    """
    dashboard = DashboardPage(owner_page)
    dashboard.wait_for_loading()
    assert dashboard.is_visible(), "Dashboard (/scouts) must be visible immediately after owner login"


@pytest.mark.smoke
def test_login_invalid_credentials(page: Page) -> None:
    """Verify that submitting wrong credentials shows an error alert.

    Uses a raw ``page`` fixture (unauthenticated) to exercise the login form
    directly.  The test confirms:
    * An alert with a non-empty message is rendered.
    * The browser stays on the ``/login`` route (no redirect on failure).
    """
    login_page = LoginPage(page)
    login_page.goto()
    login_page.login("invalid@example-test.invalid", "WrongPassword123!")

    # MUI Alert [role="alert"] must appear with an error message.
    expect(page.get_by_role("alert").first).to_be_visible(timeout=15_000)
    error_text = login_page.get_error_message()
    assert error_text, "A non-empty error message must appear for invalid credentials"
    assert "/login" in page.url, "User must remain on /login after failing authentication"


@pytest.mark.smoke
def test_logout(owner_page: Page) -> None:
    """Verify that after sign-out the browser is redirected to ``/login``.

    Relies on ``logout()`` from ``utils.auth``, which navigates to ``/settings``
    and clicks the *Sign Out* button.  The test then confirms the final URL.
    """
    logout(owner_page)
    assert "/login" in owner_page.url, "Browser must redirect to /login after the owner clicks 'Sign Out'"
