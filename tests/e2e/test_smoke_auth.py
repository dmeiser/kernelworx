"""Smoke tests for the login page UI and the sign-out flow.

The local test server does not implement ``/api/auth/login`` (no real
Cognito), so these tests verify the login page RENDERS correctly (form
fields, Google button, sign-up link) and that the authenticated *Sign out*
link redirects to ``/login``.  A real credential round-trip is out of scope
locally.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.pages.dashboard_page import DashboardPage
from tests.e2e.pages.login_page import LoginPage
from tests.e2e.utils.auth import logout


@pytest.mark.smoke
def test_login_success(owner_page: Page) -> None:
    """Verify the owner can navigate to the dashboard (``/scouts``).

    The local server treats every request as authenticated, so navigating to
    ``/scouts`` after the (fake) login lands on the authenticated dashboard.
    """
    dashboard = DashboardPage(owner_page)
    dashboard.goto()
    dashboard.wait_for_loading()
    assert dashboard.is_visible(), "Dashboard (/scouts) must be visible after navigating to the app"


@pytest.mark.smoke
def test_login_page_renders(page: Page) -> None:
    """Verify the login page renders all required form fields and options.

    Checks that:
    * The email and password inputs are visible.
    * The *Sign In* submit button is visible.
    * The *Continue with Google* button is visible.
    * The *Sign up* link is visible.
    """
    login_page = LoginPage(page)
    login_page.goto()

    expect(page.locator('input[type="email"]').first).to_be_visible(timeout=10_000)
    expect(page.locator('input[type="password"]').first).to_be_visible(timeout=10_000)
    expect(page.get_by_role("button", name="Sign In")).to_be_visible(timeout=10_000)
    assert login_page.has_google_button(), "Continue with Google button must be visible on /login"
    assert login_page.has_signup_link(), "Sign up link must be visible on /login"
    assert "/login" in page.url, "Browser must remain on /login (no redirect on initial render)"


@pytest.mark.smoke
def test_logout(owner_page: Page) -> None:
    """Verify that after sign-out the browser is redirected to ``/login``.

    Relies on ``logout()`` from ``utils.auth``, which navigates to ``/home``
    and clicks the *Sign out* link in the AppBar.  The ``auth.js`` ``logout()``
    helper sets ``window.location.href = '/login'``.
    """
    logout(owner_page)
    assert "/login" in owner_page.url, "Browser must redirect to /login after the owner clicks 'Sign out'"
